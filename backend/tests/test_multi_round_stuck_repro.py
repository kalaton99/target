"""Reproducer for the 'final 2 players stop drawing / game stuck' bug
seen in human+bot multi-round games on large-target tables.

Approach: drive a 5-seated hand (1 human + 4 bots — a 5-seat
target=61 table at full capacity, per GAME_RULES_LOCKED.md §2) all
the way from START_HAND to PAYOUT using the *actual* bot decision
rule from `_BotDriver._decide_draw_action` (HIT while score < 60% of
target), applied directly at the reducer level. We don't use
websockets at all — we simulate by inspecting `state.current_turn_seat`
and firing the appropriate action synchronously. That lets us prove
whether the reducer ever enters a state where `current_turn_seat`
becomes `None` (or points at a seat that can_draw=False) while phase
is still a draw phase.

This file exists solely to pin the bug fix; it MAY be kept as a
regression guard.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game_engine.reducer import reduce  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402


def _make_hand(target_score: int, seats: int) -> GameState:
    state = GameState(table_id="t1", target_score=target_score, stake=100)
    players = []
    players.append(
        PlayerState(seat_index=0, user_id="human", username="Human",
                    balance_at_start=10000)
    )
    for i in range(1, seats):
        players.append(
            PlayerState(seat_index=i, user_id=f"u_bot_{i}", username=f"Bot{i}",
                        balance_at_start=10000)
        )
    state.players = players
    state, _ = reduce(state, {
        "type": "START_HAND",
        "hand_id": "h1", "nonce": 0,
        "server_seed": "0" * 64, "server_seed_hash": "h" * 64,
        "client_seeds": "",
        "source": "SERVER",
    })
    return state


def _bot_draw_choice(p, target: int) -> str:
    # Match _BotDriver._decide_draw_action: HIT below 60% of target.
    hit_below = (target * 6) // 10
    return "HIT" if (p.score or 0) < hit_below else "STAND"


def _drive_to_payout(state: GameState, target: int, max_steps: int = 300):
    """Drive the hand forward with simulated bot strategy + human STAND.

    Returns the terminal state. Raises if we loop forever (detected by
    max_steps OR by observing the same state repeated) — that IS the
    bug we're pinning.
    """
    steps = 0
    seen_sigs = set()
    while state.phase not in ("PAYOUT",) and steps < max_steps:
        steps += 1
        sig = (state.phase, state.current_turn_seat, state.version,
               tuple(len(p.cards) for p in state.players))
        if sig in seen_sigs:
            raise AssertionError(
                f"STUCK STATE after {steps} steps: sig={sig} — "
                f"identical (phase, turn, version, cards) observed twice"
            )
        seen_sigs.add(sig)

        seat = state.current_turn_seat
        if seat is None:
            raise AssertionError(
                f"current_turn_seat is None while phase={state.phase} "
                f"(version={state.version}, in_hand={[p.user_id for p in state.players if p.in_hand]})"
            )
        p = state.players[seat]
        uid = p.user_id

        if state.phase in ("BETTING_R1", "BETTING_R2", "BETTING_R3"):
            # Human + bots all CHECK — we're not exercising bet logic here.
            state, _ = reduce(state, {"type": "CHECK", "user_id": uid})
            continue
        if state.phase in ("DRAW", "DRAW_1", "DRAW_2"):
            if uid == "human":
                # Human always STANDs at the first draw phase to keep
                # the test focused on bot behaviour.
                state, _ = reduce(state, {"type": "STAND", "user_id": uid})
                continue
            # Bot strategy
            choice = _bot_draw_choice(p, target)
            state, _ = reduce(state, {"type": choice, "user_id": uid})
            continue
        raise AssertionError(f"unexpected phase {state.phase}")
    assert state.phase == "PAYOUT", (
        f"did not reach PAYOUT in {max_steps} steps "
        f"(final phase={state.phase}, turn={state.current_turn_seat})"
    )
    return state


class TestStuckStateRepro:

    def test_target_61_with_1_human_and_4_bots_reaches_payout(self):
        state = _make_hand(target_score=61, seats=5)
        state = _drive_to_payout(state, target=61, max_steps=400)
        assert state.winners  # at least one winner
        # Each in_hand player must have a payout computed.
        in_hand_count = sum(1 for p in state.players if p.in_hand)
        assert in_hand_count >= 1

    def test_target_51_with_1_human_and_4_bots_reaches_payout(self):
        state = _make_hand(target_score=51, seats=5)
        state = _drive_to_payout(state, target=51, max_steps=400)
        assert state.winners

    def test_target_31_with_1_human_and_3_bots_reaches_payout(self):
        state = _make_hand(target_score=31, seats=4)
        state = _drive_to_payout(state, target=31, max_steps=200)
        assert state.winners

    def test_deck_refills_is_zero_on_target_30_hand(self):
        # Target 31 doesn't need many hits — deck should never refill.
        state = _make_hand(target_score=31, seats=4)
        state = _drive_to_payout(state, target=31, max_steps=200)
        assert state.deck_refills == 0

    def test_deck_refills_counter_survives_to_payout(self):
        # The counter is a live diagnostic that doesn't break the hand.
        # We assert it's non-negative; exact values depend on shuffle seed.
        state = _make_hand(target_score=61, seats=5)
        state = _drive_to_payout(state, target=61, max_steps=400)
        assert state.deck_refills >= 0
