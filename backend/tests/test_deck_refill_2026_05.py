"""2026-05 deck-refill rule — when the initial deck exhausts
mid-hand, the engine refills with a fresh 52-card JOKERLESS deck.
Discard pile is not reshuffled. Refills are deterministic (replays
reproduce the same card order from the same hand seed).

2026-02 update: the initial deck is now 52 + 1 Joker (= 53 cards),
not 52 + 2 (= 54). Refill behaviour is unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game_engine.reducer import reduce  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402


def _make_hand_with_empty_deck():
    """Build a hand with 2 seated players (4-seat tier minimum) whose
    initial DEAL_INITIAL + DRAW_1 will exhaust the deck on the first
    HIT, forcing a refill.

    Per GAME_RULES_LOCKED.md §2 there is no 2-seat table type;
    `n_players=2` here means a 4-seat (target=31) table with 2
    humans seated (the minimum legal start for the 4-seat tier).
    """
    state = GameState(table_id="t1", target_score=31, stake=0)
    state.players = [
        PlayerState(seat_index=0, user_id="u0", username="P0", balance_at_start=10000),
        PlayerState(seat_index=1, user_id="u1", username="P1", balance_at_start=10000),
    ]
    state, _ = reduce(state, {
        "type": "START_HAND", "hand_id": "h1", "nonce": 0,
        "server_seed": "0" * 64, "server_seed_hash": "h" * 64,
        "client_seeds": "", "source": "SERVER",
    })
    assert state.deck_refills == 0
    # CHECK through BETTING_R1 → DEAL_INITIAL → DRAW_1.
    for u in ("u0", "u1"):
        state, _ = reduce(state, {"type": "CHECK", "user_id": u})
    assert state.phase == "DRAW_1"
    # Starting deck was 53 (52 + 1 Joker); DEAL_INITIAL consumed 2 → 51 remain.
    assert len(state.deck) == 51
    # Artificially drain the deck so the next HIT triggers a refill.
    state.deck = []
    return state


class TestDeckRefill:

    def test_empty_deck_refills_on_hit(self):
        state = _make_hand_with_empty_deck()
        # HIT by whoever is on turn — triggers refill.
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        state, events = reduce(state, {"type": "HIT", "user_id": user})
        # Refill counter bumped + event emitted.
        assert state.deck_refills == 1
        refill_events = [e for e in events if e.get("type") == "DECK_REFILLED"]
        assert len(refill_events) == 1
        ev = refill_events[0]
        # New deck is 52 cards minus the one we just drew = 51.
        assert len(state.deck) == 51
        assert ev["refill_number"] == 1
        assert ev["jokers_included"] is False

    def test_refill_deck_contains_no_jokers(self):
        state = _make_hand_with_empty_deck()
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "HIT", "user_id": user})
        # Inspect all remaining cards — none may be jokers.
        for card in state.deck:
            assert card.get("rank") != "JK", f"joker found in refilled deck: {card}"

    def test_refill_is_deterministic_for_same_hand_seed(self):
        """Same commit hash + hand_id + nonce + refill counter ⇒ same
        card order. Replays reproduce."""
        def _drive_to_first_refill():
            s = _make_hand_with_empty_deck()
            seat = s.current_turn_seat
            u = s.players[seat].user_id
            s, _ = reduce(s, {"type": "HIT", "user_id": u})
            return [(c.get("rank"), c.get("suit")) for c in s.deck]

        deck_a = _drive_to_first_refill()
        deck_b = _drive_to_first_refill()
        assert deck_a == deck_b
        assert len(deck_a) == 51

    def test_start_hand_resets_refill_counter(self):
        state = _make_hand_with_empty_deck()
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "HIT", "user_id": user})
        assert state.deck_refills == 1
        # Start a fresh hand — counter must reset.
        state.phase = "WAITING"
        state.players = [
            PlayerState(seat_index=0, user_id="u0", username="P0", balance_at_start=10000),
            PlayerState(seat_index=1, user_id="u1", username="P1", balance_at_start=10000),
        ]
        state, _ = reduce(state, {
            "type": "START_HAND", "hand_id": "h2", "nonce": 0,
            "server_seed": "0" * 64, "server_seed_hash": "h" * 64,
            "client_seeds": "", "source": "SERVER",
        })
        assert state.deck_refills == 0
