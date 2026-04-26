"""Phase 2 unit tests — pure game engine only.

Scope (locked by user instruction):
  - deck creation
  - deterministic shuffle
  - draw card
  - hand score
  - HIT (via reducer)
  - STAND (via reducer)

Out of scope for these tests:
  - special cards (2/10), multi-round betting, lobby, mobile, Telegram,
    Web3, rewards, lottery, websockets, persistence, wallet.

Run from repo root:
  cd /app/backend && PYTHONPATH=. python -m pytest tests/test_engine_phase2.py -v
"""
import sys
from pathlib import Path

# Ensure /app/backend is importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from game_engine.cards import Card, SUITS, RANKS
from game_engine.deck import (
    build_fresh_deck,
    shuffle,
    compute_shuffle_seed,
)
from game_engine.scoring import score_hand
from game_engine.reducer import reduce, ReducerError
from game_engine.types import GameState, PlayerState


# ---------- DECK CREATION ----------

class TestDeckCreation:
    def test_fresh_deck_with_jokers_has_54_cards(self):
        d = build_fresh_deck(include_jokers=True)
        assert len(d) == 54

    def test_fresh_deck_without_jokers_has_52_cards(self):
        d = build_fresh_deck(include_jokers=False)
        assert len(d) == 52

    def test_fresh_deck_has_all_4_suits_x_13_ranks(self):
        d = build_fresh_deck(include_jokers=False)
        seen = {(c.rank, c.suit) for c in d}
        assert len(seen) == 52
        for s in SUITS:
            for r in RANKS:
                assert (r, s) in seen

    def test_fresh_deck_with_jokers_has_exactly_2_jokers(self):
        d = build_fresh_deck(include_jokers=True)
        jokers = [c for c in d if c.rank == "JOKER"]
        assert len(jokers) == 2

    def test_card_code_round_trip(self):
        c = Card("A", "S")
        assert c.code == "AS"
        assert Card.from_code("AS") == c
        assert Card.from_code("10H") == Card("10", "H")
        assert Card.from_code("JK") == Card("JOKER", "*")


# ---------- DETERMINISTIC SHUFFLE ----------

class TestShuffle:
    def test_same_seed_produces_same_order(self):
        d1 = build_fresh_deck()
        d2 = build_fresh_deck()
        seed = compute_shuffle_seed("a" * 64, "b" * 64, 1)
        s1 = shuffle(d1, seed)
        s2 = shuffle(d2, seed)
        assert [c.code for c in s1] == [c.code for c in s2]

    def test_different_seed_produces_different_order(self):
        d = build_fresh_deck()
        seed_a = compute_shuffle_seed("a" * 64, "x" * 64, 1)
        seed_b = compute_shuffle_seed("a" * 64, "y" * 64, 1)
        sa = shuffle(d, seed_a)
        sb = shuffle(d, seed_b)
        assert [c.code for c in sa] != [c.code for c in sb]

    def test_shuffle_preserves_all_cards(self):
        d = build_fresh_deck()
        seed = compute_shuffle_seed("z" * 64, "", 7)
        out = shuffle(d, seed)
        assert sorted(c.code for c in out) == sorted(c.code for c in d)
        assert len(out) == len(d)

    def test_compute_shuffle_seed_is_stable(self):
        a = compute_shuffle_seed("seed", "client", 42)
        b = compute_shuffle_seed("seed", "client", 42)
        assert a == b

    def test_compute_shuffle_seed_changes_with_nonce(self):
        a = compute_shuffle_seed("seed", "client", 1)
        b = compute_shuffle_seed("seed", "client", 2)
        assert a != b


# ---------- DRAW CARD ----------

class TestDrawCard:
    def test_draw_pops_first_card(self):
        d = build_fresh_deck()
        original = d[0]
        drawn = d.pop(0)
        assert drawn == original
        assert len(d) == 53

    def test_can_drain_entire_deck(self):
        d = build_fresh_deck()
        cards = []
        while d:
            cards.append(d.pop(0))
        assert len(cards) == 54
        assert d == []


# ---------- HAND SCORE ----------

def C(rank, suit="S"):
    return {"rank": rank, "suit": suit, "code": f"{rank}{suit}"}


class TestScoring:
    def test_number_cards_face_value(self):
        s = score_hand([C("2"), C("3"), C("9")])
        assert s == {"total": 14, "soft": False, "busted": False, "disqualified": False}

    def test_ten_is_ten(self):
        s = score_hand([C("10"), C("10")])
        assert s["total"] == 20
        assert s["busted"] is False

    def test_jack_is_seven(self):
        assert score_hand([C("J")])["total"] == 7

    def test_queen_is_eight(self):
        assert score_hand([C("Q")])["total"] == 8

    def test_king_is_nine(self):
        assert score_hand([C("K")])["total"] == 9

    def test_ace_alone_is_eleven_when_safe(self):
        s = score_hand([C("A")])
        assert s["total"] == 11
        assert s["soft"] is True

    def test_ace_demotes_to_one_to_avoid_bust(self):
        # A + 10 + 5 = 16 if Ace=1; would be 26 if Ace=11
        s = score_hand([C("A"), C("10"), C("5")])
        assert s["total"] == 16
        assert s["soft"] is False
        assert s["busted"] is False

    def test_two_aces_one_high_one_low(self):
        # A=11 + A=1 = 12
        s = score_hand([C("A"), C("A")])
        assert s["total"] == 12
        assert s["soft"] is True

    def test_blackjack_ace_plus_ten(self):
        s = score_hand([C("A"), C("10")])
        assert s["total"] == 21
        assert s["busted"] is False

    def test_bust_detection(self):
        s = score_hand([C("10"), C("8"), C("5")])
        assert s["total"] == 23
        assert s["busted"] is True

    def test_joker_disqualified(self):
        s = score_hand([C("5"), C("JOKER", "*")])
        assert s["disqualified"] is True
        # Per implementation, busted is False when DQ short-circuits
        assert s["busted"] is False

    def test_face_cards_combo_no_bust(self):
        # K(9) + Q(8) = 17
        s = score_hand([C("K"), C("Q")])
        assert s["total"] == 17
        assert s["busted"] is False


# ---------- REDUCER: HIT / STAND ----------

def _make_state_two_players():
    """Minimal DRAW-phase state with 2 players, deck primed."""
    state = GameState(
        table_id="t_test",
        hand_id="h_test",
        engine_version="1.0.0",
        phase="DRAW",
        version=10,
        players=[
            PlayerState(seat_index=0, user_id="u1", username="p1", balance_at_start=1000,
                        cards=[C("5"), C("3")], score=8),
            PlayerState(seat_index=1, user_id="u2", username="p2", balance_at_start=1000,
                        cards=[C("9"), C("7")], score=16),
        ],
        deck=[C("4"), C("2"), C("10"), C("J")],
        pot=200,
        stake=100,
        current_turn_seat=0,
    )
    return state


class TestHit:
    def test_hit_appends_card_and_updates_score(self):
        state = _make_state_two_players()
        new_state, events = reduce(state, {
            "type": "HIT",
            "user_id": "u1",
            "state_version": state.version,
            "source": "CLIENT",
        })
        # Original 5+3=8 + 4 = 12
        p = new_state.players[0]
        assert len(p.cards) == 3
        assert p.score == 12
        assert p.busted is False
        assert any(e["type"] == "CARD_DRAWN" for e in events)
        assert new_state.version == state.version + 1
        # Same player still on turn (not stood, not busted)
        assert new_state.current_turn_seat == 0

    def test_hit_only_allowed_on_own_turn(self):
        state = _make_state_two_players()
        with pytest.raises(ReducerError):
            reduce(state, {
                "type": "HIT",
                "user_id": "u2",  # not their turn
                "state_version": state.version,
                "source": "CLIENT",
            })

    def test_hit_to_bust_advances_turn(self):
        state = _make_state_two_players()
        # Force a bust: 5+3+10+J = 5+3+10+7 = 25
        state.deck = [C("10"), C("J"), C("4")]
        state.version = 5
        new_state, _ = reduce(state, {
            "type": "HIT", "user_id": "u1",
            "state_version": state.version, "source": "CLIENT",
        })
        # 5+3+10 = 18 (no bust yet)
        assert new_state.players[0].busted is False
        # Hit again
        ns2, _ = reduce(new_state, {
            "type": "HIT", "user_id": "u1",
            "state_version": new_state.version, "source": "CLIENT",
        })
        # 18+7 = 25 -> bust
        assert ns2.players[0].busted is True
        # Auto-advanced
        assert ns2.players[0].stood is True
        assert ns2.current_turn_seat == 1

    def test_hit_wrong_phase_rejected(self):
        state = _make_state_two_players()
        state.phase = "BETTING"
        with pytest.raises(ReducerError):
            reduce(state, {
                "type": "HIT", "user_id": "u1",
                "state_version": state.version, "source": "CLIENT",
            })


class TestStand:
    def test_stand_locks_player_and_advances_turn(self):
        state = _make_state_two_players()
        new_state, events = reduce(state, {
            "type": "STAND",
            "user_id": "u1",
            "state_version": state.version,
            "source": "CLIENT",
        })
        assert new_state.players[0].stood is True
        assert new_state.current_turn_seat == 1
        assert new_state.version == state.version + 1
        assert any(e["type"] == "STAND" for e in events)

    def test_stand_rejected_if_not_your_turn(self):
        state = _make_state_two_players()
        with pytest.raises(ReducerError):
            reduce(state, {
                "type": "STAND",
                "user_id": "u2",
                "state_version": state.version,
                "source": "CLIENT",
            })

    def test_both_stand_advances_to_betting(self):
        state = _make_state_two_players()
        s1, _ = reduce(state, {
            "type": "STAND", "user_id": "u1",
            "state_version": state.version, "source": "CLIENT",
        })
        s2, _ = reduce(s1, {
            "type": "STAND", "user_id": "u2",
            "state_version": s1.version, "source": "CLIENT",
        })
        assert s2.phase == "BETTING"


class TestServerOnlyGuard:
    def test_client_cannot_send_auto_stand_timeout(self):
        state = _make_state_two_players()
        with pytest.raises(ReducerError):
            reduce(state, {
                "type": "AUTO_STAND_TIMEOUT",
                "user_id": "u1",
                "seat_index": 0,
                "state_version": state.version,
                "source": "CLIENT",  # not SERVER
            })

    def test_server_can_emit_auto_stand_timeout(self):
        state = _make_state_two_players()
        new_state, events = reduce(state, {
            "type": "AUTO_STAND_TIMEOUT",
            "user_id": "u1",
            "seat_index": 0,
            "state_version": state.version,
            "source": "SERVER",
            "payload": {"reason": "TURN_TIMEOUT_15S"},
        })
        # Result is STAND, never FOLD
        assert new_state.players[0].stood is True
        assert new_state.players[0].folded is False
        ev = next(e for e in events if e["type"] == "STAND")
        assert ev["auto"] is True
        assert ev["reason"] == "TURN_TIMEOUT_15S"
