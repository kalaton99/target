"""2026-05 v2 — Gameplay balance simulations.

Drives many hands at each locked target, with 1 human + max bots, using
the *production* bot policy copied inline (keeps the test independent
from network I/O and asyncio). Asserts:

  - Every hand terminates in PAYOUT within a bounded step budget.
  - No `(phase, turn, version, card_counts)` signature repeats within a
    single hand (infinite-loop detector — same check as the stuck-repro
    test, tightened).
  - Average hand length is in a plausible band (diagnostic, not tight).
  - Winner distribution is not trivially degenerate (at least two
    distinct seats win across 30 hands — guards against a bug that
    forces the same seat to always win).
  - Bust rate is < 80% (would indicate bots HIT forever).

The "gameplay balance report" is printed to stdout on success so the
test log doubles as a human-readable diagnostic.
"""
from __future__ import annotations

import hashlib
import random
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.constants import TABLE_SEATS_BY_TARGET, max_bots_for_target  # noqa: E402
from game_engine.reducer import reduce  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402


# ---------- bot policy (mirror of _BotDriver._decide_draw_action) ----------

def _bot_draw_choice(
    target: int, score: int, *, table_id: str, bot_user_id: str, sv: int,
) -> str:
    if score >= target:
        return "STAND"
    upper = (target * 8) // 10
    lower = (target * 5) // 10
    if score >= upper:
        return "STAND"
    if score < lower:
        return "HIT"
    seed = f"{table_id}:{bot_user_id}:{sv}".encode("utf-8")
    roll = int(hashlib.sha1(seed).hexdigest()[-4:], 16) % 100
    return "HIT" if roll < 60 else "STAND"


# ---------- helpers ----------

def _make_hand(table_id: str, target: int, n_bots: int, hand_id: str) -> GameState:
    """1 human + n_bots seated; uses a deterministic seed per hand_id."""
    seats = 1 + n_bots
    state = GameState(table_id=table_id, target_score=target, stake=100)
    players = [
        PlayerState(seat_index=0, user_id="human", username="Human",
                    balance_at_start=10_000)
    ]
    for i in range(1, seats):
        players.append(
            PlayerState(seat_index=i, user_id=f"u_bot_{i}",
                        username=f"Bot{i}", balance_at_start=10_000)
        )
    state.players = players

    # Deterministic RNG seed → reproducible shuffle per hand_id.
    seed = int(hashlib.sha256(hand_id.encode("utf-8")).hexdigest()[:16], 16)
    state, _ = reduce(state, {
        "type": "START_HAND",
        "hand_id": hand_id,
        "nonce": seed & 0xFFFFFFFF,
        "server_seed": hashlib.sha256(hand_id.encode()).hexdigest() * 2,  # 128 hex → crop
        "server_seed_hash": "h" * 64,
        "client_seeds": "",
        "source": "SERVER",
    })
    return state


def _drive_to_payout(state: GameState, target: int, max_steps: int = 500) -> Tuple[GameState, int]:
    """Drive a hand until PAYOUT using the production bot policy for bots
    and a pure-CHECK / STAND strategy for the human (so variance comes
    from bot strategy + shuffle, not human tactical play).

    Returns (final_state, action_count).
    """
    steps = 0
    seen: set = set()
    while state.phase != "PAYOUT" and steps < max_steps:
        steps += 1
        sig = (state.phase, state.current_turn_seat, state.version,
               tuple(len(p.cards) for p in state.players))
        if sig in seen:
            raise AssertionError(
                f"INFINITE-LOOP: repeated sig after {steps} steps: {sig}"
            )
        seen.add(sig)

        seat = state.current_turn_seat
        if seat is None:
            raise AssertionError(
                f"TURN_NONE: phase={state.phase} version={state.version}"
            )
        p = state.players[seat]
        uid = p.user_id

        if state.phase in ("BETTING_R1", "BETTING_R2", "BETTING_R3"):
            # Everyone CHECKs — not exercising bet logic in the balance sim.
            state, _ = reduce(state, {"type": "CHECK", "user_id": uid})
            continue
        if state.phase in ("DRAW", "DRAW_1", "DRAW_2"):
            if uid == "human":
                state, _ = reduce(state, {"type": "STAND", "user_id": uid})
                continue
            choice = _bot_draw_choice(
                target, p.score or 0,
                table_id=state.table_id,
                bot_user_id=uid,
                sv=state.version,
            )
            state, _ = reduce(state, {"type": choice, "user_id": uid})
            continue
        raise AssertionError(f"unexpected phase {state.phase}")

    assert state.phase == "PAYOUT", (
        f"did NOT reach PAYOUT in {max_steps} steps "
        f"(phase={state.phase}, turn={state.current_turn_seat})"
    )
    return state, steps


# ---------- simulations ----------

HANDS_PER_CONFIG = 30


@pytest.mark.parametrize("target", [30, 50, 75, 100])
def test_balance_sim_target_with_max_bots(target: int):
    """Simulate HANDS_PER_CONFIG hands for each locked target with max bots.

    Asserts termination, no loops, and plausible bust / winner spread.
    Prints a one-line report per config to the pytest output.
    """
    seats = TABLE_SEATS_BY_TARGET[target]
    # 1 human + (seats - 1) bots.
    n_bots = seats - 1
    # sanity: lobby would clamp by max_bots_for_target too.
    assert n_bots <= max_bots_for_target(target), (
        f"sim config uses more bots than lobby would allow: {n_bots} > "
        f"{max_bots_for_target(target)}"
    )

    step_counts: List[int] = []
    winner_seats: List[int] = []
    bust_count = 0
    finalized_hands = 0

    for i in range(HANDS_PER_CONFIG):
        hand_id = f"bal_t{target}_{i:03d}"
        state = _make_hand(
            table_id=f"tbl_{hand_id}",
            target=target,
            n_bots=n_bots,
            hand_id=hand_id,
        )
        final, steps = _drive_to_payout(state, target, max_steps=500)
        step_counts.append(steps)
        winners = final.winners or []
        if winners:
            # Record seat of first listed winner (ties are rare & not
            # meaningful for distribution sanity).
            for p in final.players:
                if p.user_id == winners[0]:
                    winner_seats.append(p.seat_index)
                    break
        bust_count += sum(1 for p in final.players if p.busted)
        finalized_hands += 1

    # --- assertions ---
    assert finalized_hands == HANDS_PER_CONFIG
    # Winner distribution: at least 2 distinct seats must win over 30 hands.
    # (Any single seat dominating is a red flag for a broken shuffle.)
    distinct = len(set(winner_seats))
    assert distinct >= 2, (
        f"target={target}: only {distinct} distinct winner seat(s) "
        f"over {HANDS_PER_CONFIG} hands — suspicious"
    )
    # Bust rate: well below runaway.
    total_player_slots = finalized_hands * (n_bots + 1)
    bust_rate = bust_count / total_player_slots
    assert bust_rate < 0.8, (
        f"target={target}: bust_rate={bust_rate:.2%} is absurdly high "
        f"— bot policy likely mis-configured"
    )
    # Hand length sanity: at least 3 actions (tiniest hand: R1+DRAW_1 stand
    # through with 2 players ≈ 6), and below our 500-step budget.
    mean_len = statistics.mean(step_counts)
    max_len = max(step_counts)
    assert 3 < mean_len < 500
    assert max_len < 500

    # Diagnostic report — shows up in pytest -s output.
    seat_hist: Dict[int, int] = {}
    for s in winner_seats:
        seat_hist[s] = seat_hist.get(s, 0) + 1
    print(
        f"\n[BAL target={target} seats={seats} bots={n_bots} hands={HANDS_PER_CONFIG}] "
        f"mean_steps={mean_len:.1f} max_steps={max_len} "
        f"bust_rate={bust_rate:.1%} "
        f"winner_seats={sorted(seat_hist.items())}"
    )


def test_balance_sim_no_shuffle_determinism_regression():
    """Same hand_id twice → identical outcome. Pins determinism so
    replays don't diverge after a refactor.
    """
    hand_id = "bal_det_check_001"
    a = _make_hand(table_id=f"tbl_{hand_id}", target=100, n_bots=4, hand_id=hand_id)
    b = _make_hand(table_id=f"tbl_{hand_id}", target=100, n_bots=4, hand_id=hand_id)
    a_final, _ = _drive_to_payout(a, 100)
    b_final, _ = _drive_to_payout(b, 100)
    assert a_final.winners == b_final.winners
    # Final scores must match seat-by-seat.
    assert [p.score for p in a_final.players] == [p.score for p in b_final.players]
