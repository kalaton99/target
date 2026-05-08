"""2026-02 Joker count regression test.

Rule (locked):
  - Initial deck = 52 standard + exactly **1** Joker (53 cards).
  - Refill deck   = 52 standard + **0** Jokers.
  - A single active hand/deck sequence must never produce two Jokers
    before a refill — the old 52+2 layout is removed.

Targeted regression. Does not exercise the wider engine.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game_engine.deck import build_fresh_deck  # noqa: E402
from game_engine.reducer import reduce  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402


def _count_jokers(cards):
    return sum(1 for c in cards if (
        getattr(c, "rank", None) == "JOKER" or
        (isinstance(c, dict) and c.get("rank") == "JOKER")
    ))


class TestJokerCount:

    def test_initial_deck_has_exactly_one_joker(self):
        deck = build_fresh_deck(include_jokers=True)
        assert len(deck) == 53, f"expected 53 cards (52+1 Joker), got {len(deck)}"
        assert _count_jokers(deck) == 1

    def test_refill_deck_has_zero_jokers(self):
        deck = build_fresh_deck(include_jokers=False)
        assert len(deck) == 52
        assert _count_jokers(deck) == 0

    def test_initial_deck_after_start_hand_has_one_joker(self):
        """Engine end-to-end: after START_HAND the per-table deck must
        contain exactly one Joker — the rule applies through the full
        shuffle path, not just the raw builder.
        """
        state = GameState(table_id="t1", target_score=30, stake=0)
        state.players = [
            PlayerState(seat_index=0, user_id="u0", username="P0", balance_at_start=10000),
            PlayerState(seat_index=1, user_id="u1", username="P1", balance_at_start=10000),
        ]
        state, _ = reduce(state, {
            "type": "START_HAND", "hand_id": "h1", "nonce": 0,
            "server_seed": "0" * 64, "server_seed_hash": "h" * 64,
            "client_seeds": "", "source": "SERVER",
        })
        # Pre-DEAL_INITIAL the deck holds the full shuffled 53.
        # After CHECK round → DEAL_INITIAL has consumed `n_players`
        # cards; for a 2-seated 4-seat table that is 2 → 51 remain.
        # The Joker count across (deck + dealt hands) must be 1 — the
        # Joker can never duplicate.
        for u in ("u0", "u1"):
            state, _ = reduce(state, {"type": "CHECK", "user_id": u})
        deck_jokers = _count_jokers(state.deck)
        hand_jokers = sum(_count_jokers(p.cards) for p in state.players)
        assert deck_jokers + hand_jokers == 1, (
            f"hand must contain exactly one Joker across deck+hands; "
            f"got deck={deck_jokers}, hands={hand_jokers}"
        )

    def test_no_two_jokers_emerge_in_active_sequence(self):
        """Across a long DRAW sequence in a single hand, the running
        total of Jokers ever seen (deck + all player hands, deduped by
        identity) must remain ≤ 1 until a refill occurs. We approximate
        this by walking the deck pre-DEAL_INITIAL plus what's already
        been dealt: at any moment, the union has ≤ 1 Joker.
        """
        state = GameState(table_id="t1", target_score=30, stake=0)
        state.players = [
            PlayerState(seat_index=0, user_id="u0", username="P0", balance_at_start=10000),
            PlayerState(seat_index=1, user_id="u1", username="P1", balance_at_start=10000),
        ]
        state, _ = reduce(state, {
            "type": "START_HAND", "hand_id": "h1", "nonce": 0,
            "server_seed": "0" * 64, "server_seed_hash": "h" * 64,
            "client_seeds": "", "source": "SERVER",
        })
        # Sanity at initial-shuffled-deck level.
        assert _count_jokers(state.deck) == 1
        # Walk through CHECK round + DEAL_INITIAL + a few HITs.
        for u in ("u0", "u1"):
            state, _ = reduce(state, {"type": "CHECK", "user_id": u})
        for _ in range(4):
            seat = state.current_turn_seat
            if seat is None:
                break
            user = state.players[seat].user_id
            state, _ = reduce(state, {"type": "HIT", "user_id": user})
            if state.deck_refills > 0:
                # Refill happened — by rule, refill is jokerless. Past
                # the refill the invariant "at most 1 joker before
                # refill" no longer constrains the new deck (it's 0).
                break
            total = _count_jokers(state.deck) + sum(
                _count_jokers(p.cards) for p in state.players
            )
            assert total <= 1, f"more than one Joker in active sequence: {total}"
