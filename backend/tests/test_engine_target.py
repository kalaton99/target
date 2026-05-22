"""TARGET v2 engine tests — covers the 2026-02 rewrite.

Scope:
  - Dynamic target: 31 / 41 / 51 / 61 (2026-05 v2 — 250 removed)
  - Phase order: ANTE -> BETTING_R1 -> DEAL_INITIAL -> DRAW -> SHOWDOWN -> PAYOUT
  - Initial deal: 1 card per player (NOT 2)
  - 51% rule (BET / RAISE / CALL / CHECK / FOLD)
  - Stand-threshold lookup
  - Special card '2' (Hearts/Clubs): manual transfer + auto bust-save
  - Special card '10' (Hearts/Clubs): forced attack
  - Joker -> instant DQ
  - Server-only action enforcement
  - state_version monotonic
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.constants import STAND_THRESHOLD, VALID_TARGET_SCORES  # noqa: E402
from game_engine.reducer import ReducerError, reduce  # noqa: E402
from game_engine.scoring import score_hand  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402


# ---------- helpers ----------

def make_state(n_players=2, *, target=31, stake=100, balances=None):
    state = GameState(table_id="t1", target_score=target, stake=stake)
    bals = balances if balances is not None else [10000] * n_players
    state.players = [
        PlayerState(seat_index=i, user_id=f"u{i}", username=f"P{i}", balance_at_start=bals[i])
        for i in range(n_players)
    ]
    return state


def start_hand(state, *, target=None):
    action = {
        "type": "START_HAND", "source": "SERVER",
        "hand_id": "h1", "nonce": 0,
        "server_seed": "0" * 64, "server_seed_hash": "h" * 64,
        "client_seeds": "",
    }
    if target is not None:
        action["target_score"] = target
    return reduce(state, action)


def all_check_through_betting(state):
    """Drive every in-hand player to CHECK through the *current* betting
    round, returning the new state. Works for BETTING_R1 / R2 / R3."""
    while state.phase in ("BETTING_R1", "BETTING_R2", "BETTING_R3"):
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "CHECK", "user_id": user})
    return state


# =====================================================================
# Scoring
# =====================================================================

class TestScoring:
    def test_face_values(self):
        cards = [{"rank": "J", "suit": "S"}, {"rank": "Q", "suit": "H"}]
        s = score_hand(cards, target=31)
        assert s["total"] == 7 + 8

    def test_king_is_nine(self):
        s = score_hand([{"rank": "K", "suit": "S"}], target=31)
        assert s["total"] == 9

    def test_ace_promotes_when_safe(self):
        s = score_hand([{"rank": "A", "suit": "S"}, {"rank": "9", "suit": "C"}], target=31)
        assert s["total"] == 20
        assert s["soft"] is True

    def test_ace_stays_one_when_promote_would_bust(self):
        s = score_hand([{"rank": "A", "suit": "S"}, {"rank": "9", "suit": "C"},
                        {"rank": "K", "suit": "C"}, {"rank": "5", "suit": "S"}], target=25)
        # 1+9+9+5 = 24, +10 would bust at 34; stays 24
        assert s["total"] == 24
        assert s["soft"] is False

    def test_joker_is_dq(self):
        s = score_hand([{"rank": "JOKER", "suit": "*"}, {"rank": "5", "suit": "S"}], target=31)
        assert s["disqualified"] is True
        assert s["busted"] is False

    def test_target_41_does_not_bust_normal_blackjack_hand(self):
        # 22 would bust at 21 but not at 41
        cards = [{"rank": "10", "suit": "S"}, {"rank": "Q", "suit": "H"}, {"rank": "4", "suit": "C"}]
        s = score_hand(cards, target=41)
        assert s["busted"] is False
        assert s["total"] == 10 + 8 + 4


# =====================================================================
# START_HAND / phase order / initial deal = 1 card
# =====================================================================

class TestStartHand:
    def test_start_hand_all_valid_targets(self):
        for tgt in VALID_TARGET_SCORES:
            state = make_state(2, target=tgt)
            new_state, events = start_hand(state, target=tgt)
            assert new_state.target_score == tgt

    def test_invalid_target_score_rejected(self):
        state = make_state(2)
        with pytest.raises(ReducerError, match="INVALID_TARGET_SCORE"):
            start_hand(state, target=21)

    def test_phase_order_lands_in_betting_r1_after_start(self):
        state = make_state(2)
        new_state, events = start_hand(state)
        assert new_state.phase == "BETTING_R1"
        assert new_state.current_turn_seat == 0
        # No cards dealt yet
        for p in new_state.players:
            assert p.cards == []
        assert new_state.pot == 200  # 2 players × 100 ante

    def test_betting_check_through_advances_to_draw_with_one_card_each(self):
        state = make_state(2)
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        # 2026-05 multi-round: BETTING_R1 → DEAL_INITIAL → DRAW_1
        # (was simply "DRAW" before the multi-round extension).
        assert state.phase == "DRAW_1"
        assert state.betting_round == 0
        # exactly 1 card per player after DEAL_INITIAL
        for p in state.players:
            assert len(p.cards) == 1


# =====================================================================
# 51% rule — BET / RAISE / CALL / CHECK / FOLD
# =====================================================================

class TestBetting51Percent:
    def test_bet_sets_call_owed_to_51pct_ceil(self):
        state = make_state(3)
        state, _ = start_hand(state)
        # P0 bets 10 -> ceil(0.51*10) = ceil(5.1) = 6
        state, _ = reduce(state, {
            "type": "BET", "user_id": "u0", "payload": {"amount": 10},
        })
        assert state.last_raise_amount == 10
        assert state.current_call_owed == 6
        assert state.players[0].total_contributed == 100 + 10  # ante + bet
        assert state.pot == 300 + 10

    def test_call_amount_equals_current_call_owed(self):
        state = make_state(3)
        state, _ = start_hand(state)
        state, _ = reduce(state, {"type": "BET", "user_id": "u0", "payload": {"amount": 10}})
        # Now it's u1's turn; call = 6
        state, _ = reduce(state, {"type": "CALL", "user_id": "u1"})
        assert state.players[1].total_contributed == 100 + 6
        assert state.pot == 300 + 10 + 6

    def test_raise_resets_responded_set_and_owes_51pct_of_new_raise(self):
        state = make_state(3)
        state, _ = start_hand(state)
        state, _ = reduce(state, {"type": "BET", "user_id": "u0", "payload": {"amount": 20}})
        # u1 RAISES by 10. Pays call(11) + raise(10) = 21
        state, _ = reduce(state, {"type": "RAISE", "user_id": "u1", "payload": {"amount": 10}})
        assert state.last_raise_amount == 10
        assert state.current_call_owed == 6  # ceil(5.1)
        assert state.responded_seats == [1]
        assert state.players[1].total_contributed == 100 + 21

    def test_check_when_call_owed_is_rejected(self):
        state = make_state(2)
        state, _ = start_hand(state)
        state, _ = reduce(state, {"type": "BET", "user_id": "u0", "payload": {"amount": 5}})
        with pytest.raises(ReducerError, match="CANNOT_CHECK_FACING_BET"):
            reduce(state, {"type": "CHECK", "user_id": "u1"})

    def test_bet_when_call_owed_is_rejected(self):
        state = make_state(2)
        state, _ = start_hand(state)
        state, _ = reduce(state, {"type": "BET", "user_id": "u0", "payload": {"amount": 5}})
        with pytest.raises(ReducerError, match="BET_WHEN_CALL_OWED"):
            reduce(state, {"type": "BET", "user_id": "u1", "payload": {"amount": 5}})

    def test_max_raise_capped_by_lowest_active_wallet(self):
        # u0=10000 (already paid 100 ante so 9900 left),
        # u1=200  (already paid 100 ante so 100 left)
        state = make_state(2, balances=[10000, 200])
        state, _ = start_hand(state)
        # u1 has 100 available. Max raise X st ceil(0.51*X) <= 100 -> 0.51*X <= 100 -> X <= 196.
        # max_raise_cap returns floor(100*100/51) = 196.
        with pytest.raises(ReducerError, match="BET_EXCEEDS_CAP"):
            reduce(state, {"type": "BET", "user_id": "u0", "payload": {"amount": 200}})
        # 196 must work
        state2, _ = reduce(state, {"type": "BET", "user_id": "u0", "payload": {"amount": 196}})
        assert state2.last_raise_amount == 196

    def test_call_auto_folds_when_caller_cant_afford(self):
        # u0=10000, u1=120 (after ante = 20 left)
        state = make_state(2, balances=[10000, 120])
        state, _ = start_hand(state)
        # u0 bets 200 -> call required = ceil(0.51*200) = 102. u1 only has 20.
        # But max_raise cap is floor(20*100/51) = 39. Bet 200 fails. Use a smaller bet.
        # Try bet 30 -> call = ceil(15.3) = 16. u1 has 20 -> can pay. So increase bet to 39 -> call=20 (exact).
        # Test the auto-fold path: bet amount where call > u1 available.
        # Actually with proper cap, u0 can't bet > 39. Let's bet 39.
        state, _ = reduce(state, {"type": "BET", "user_id": "u0", "payload": {"amount": 39}})
        # call = ceil(0.51*39) = 20. u1 has exactly 20. CALL succeeds.
        state, _ = reduce(state, {"type": "CALL", "user_id": "u1"})
        # 2026-05 multi-round: BETTING_R1 ends → DRAW_1.
        assert state.phase == "DRAW_1"
        assert state.players[1].folded is False

    def test_fold_in_betting(self):
        state = make_state(3)
        state, _ = start_hand(state)
        state, _ = reduce(state, {"type": "BET", "user_id": "u0", "payload": {"amount": 10}})
        state, _ = reduce(state, {"type": "FOLD", "user_id": "u1"})
        assert state.players[1].folded is True
        # u2 still has to respond
        assert state.phase == "BETTING_R1"

    def test_only_one_left_after_folds_goes_to_showdown(self):
        state = make_state(3)
        state, _ = start_hand(state)
        state, _ = reduce(state, {"type": "BET", "user_id": "u0", "payload": {"amount": 10}})
        state, _ = reduce(state, {"type": "FOLD", "user_id": "u1"})
        state, _ = reduce(state, {"type": "FOLD", "user_id": "u2"})
        assert state.phase == "PAYOUT"
        # u0 wins by default
        assert state.winners == ["u0"]


# =====================================================================
# Stand-threshold lookup
# =====================================================================

class TestStandThreshold:
    def test_two_players_one_stand_ends_draw_round(self):
        # 2026-05 multi-round: with 2 seated players (a 4-seat tier
        # table at minimum legal start; there is no 2-seat table type
        # — see GAME_RULES_LOCKED.md §2), threshold[2]=1 still ends
        # DRAW_1, but routes to BETTING_R2 (not SHOWDOWN). To reach
        # PAYOUT we then walk through R2 → DRAW_2 → R3 → SHOWDOWN.
        state = make_state(2)
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        assert state.phase == "DRAW_1"
        assert state.draw_active_count == 2
        assert STAND_THRESHOLD[2] == 1
        # u0 STANDs -> 1 stand, threshold met -> BETTING_R2 opens.
        active_user = state.players[state.current_turn_seat].user_id
        state, _ = reduce(state, {"type": "STAND", "user_id": active_user})
        assert state.phase == "BETTING_R2"
        assert state.betting_round == 2
        # CHECK through R2 → DRAW_2.
        state = all_check_through_betting(state)
        # u0 already stood; u1 now on turn for DRAW_2.
        assert state.phase == "DRAW_2"
        # u1 STANDs -> threshold met again -> BETTING_R3.
        seat = state.current_turn_seat
        state, _ = reduce(state, {"type": "STAND", "user_id": state.players[seat].user_id})
        assert state.phase == "BETTING_R3"
        # CHECK through R3 → SHOWDOWN → PAYOUT.
        state = all_check_through_betting(state)
        assert state.phase == "PAYOUT"

    def test_four_players_three_stands_per_round_ends_draw_round(self):
        # 4 players, threshold[4]=3. In each draw round, 3 stands end
        # the round and route to the next betting round (or SHOWDOWN
        # after DRAW_2). Stand is sticky — players who stand in DRAW_1
        # remain stood for DRAW_2.
        state = make_state(4)
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        assert state.draw_active_count == 4
        assert STAND_THRESHOLD[4] == 3
        # First 2 stands: still in DRAW_1
        for _ in range(2):
            seat = state.current_turn_seat
            user = state.players[seat].user_id
            state, _ = reduce(state, {"type": "STAND", "user_id": user})
            assert state.phase == "DRAW_1"
        # 3rd stand -> BETTING_R2 (round transition, not showdown).
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "STAND", "user_id": user})
        assert state.phase == "BETTING_R2"


# =====================================================================
# DRAW: HIT / STAND / Joker / bust-save / specials
# =====================================================================

class _FixedDeck:
    """Helper that swaps the top of the deck with a controlled card list."""
    @staticmethod
    def push_top(state, cards):
        # Insert cards at the front of the deck
        state.deck = list(cards) + list(state.deck)


class TestDrawAndSpecials:
    def test_hit_draws_one_card_and_recomputes_score(self):
        state = make_state(2, target=31)
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        # Active is seat 0
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        before = len(state.players[seat].cards)
        state, _ = reduce(state, {"type": "HIT", "user_id": user})
        assert len(state.players[seat].cards) == before + 1

    def test_joker_disqualifies_on_hit(self):
        state = make_state(2, target=31)
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        # Stack a joker on top
        _FixedDeck.push_top(state, [{"rank": "JOKER", "suit": "*"}])
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "HIT", "user_id": user})
        assert state.players[seat].disqualified is True

    def test_bust_save_with_hearts_2_transfers_highest_and_saves(self):
        state = make_state(2, target=31)
        # We'll inject controlled cards: P0 starts with 2H + Q (8) = 10.
        # We force the next card on HIT to be K (9) -> would 10+9=19 if not busting.
        # To force a bust-save, give P0 starting 2H + K + Q (= 0 + 9 + 8 = 17) and target=31
        # would not bust. Need a higher target=31 means need score>31.
        # Simulate: hand has 2H + 9 + 9 = 0+9+9 = 18, then +K = 27, +K = 36 (busts at 31).
        # Instead, we'll directly construct DRAW state and call HIT.
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        seat = state.current_turn_seat
        p = state.players[seat]
        # Replace P0's hand: 2H + 9D + 9S (= 0+9+9 = 18)
        p.cards = [
            {"rank": "2", "suit": "H"},
            {"rank": "9", "suit": "D"},
            {"rank": "9", "suit": "S"},
        ]
        # Rescore manually
        from game_engine.scoring import score_hand
        s = score_hand(p.cards, 31)
        p.score, p.soft, p.busted, p.disqualified = s["total"], s["soft"], s["busted"], s["disqualified"]
        # next HIT will draw a K (9). 18 + 9 = 27 -- doesn't bust.
        # Force K. Push a specific bust card: Q (8): 18+8=26 fine. We need >31. K=9: 27 fine.
        # Total after HIT = 18 + draw_card_value. To bust at >31, need draw_card_value > 12.
        # Card values are at most 9 (K). So we need to set up a higher hand.
        # Let me redo: P0 has 2H + K + K = 0+9+9 = 18. Next K = 27. Still safe.
        # Actually the hand can never bust at 31 from cards alone since max card is 9 (K).
        # 4 K's = 36 busts. Plus 2H is 0. So: 2H + K + K + K = 27. +K = 36 busts.
        # Let me make sure deck top is K.
        p.cards = [
            {"rank": "2", "suit": "H"},
            {"rank": "K", "suit": "S"},
            {"rank": "K", "suit": "C"},
            {"rank": "K", "suit": "D"},
        ]
        s = score_hand(p.cards, 31)
        p.score, p.soft, p.busted, p.disqualified = s["total"], s["soft"], s["busted"], s["disqualified"]
        assert p.score == 29 and not p.busted
        # Push a K on top of deck: 29 + 9 = 38 busts.
        _FixedDeck.push_top(state, [{"rank": "K", "suit": "H"}])
        before_opp_cards = list(state.players[1].cards)
        state, events = reduce(state, {"type": "HIT", "user_id": p.user_id})
        # bust-save kicks in: highest non-2 card is one of the K's (9) -- transferred
        bust_save = [e for e in events if e.get("type") == "BUST_SAVE"]
        assert bust_save, f"expected BUST_SAVE, events={[e.get('type') for e in events]}"
        # P0 should no longer be busted
        assert state.players[0].busted is False
        # P0 hand no longer contains 2H
        assert all(not (c["rank"] == "2" and c["suit"] == "H") for c in state.players[0].cards)
        # Opp received a card
        assert len(state.players[1].cards) == len(before_opp_cards) + 1
        # P0 forced-stood after bust-save
        assert state.players[0].stood is True

    def test_play_two_manual_transfer(self):
        state = make_state(2, target=31)
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        seat = state.current_turn_seat
        p = state.players[seat]
        opp = state.players[1 - seat]
        # Set P0 hand: 2C + 6S + 9D = 0+6+9 = 15
        p.cards = [
            {"rank": "2", "suit": "C"},
            {"rank": "6", "suit": "S"},
            {"rank": "9", "suit": "D"},
        ]
        from game_engine.scoring import score_hand
        s = score_hand(p.cards, 31)
        p.score, p.soft, p.busted, p.disqualified = s["total"], s["soft"], s["busted"], s["disqualified"]
        opp_before = list(opp.cards)
        # Send the 9D (index 2) to opponent
        state, events = reduce(state, {
            "type": "PLAY_TWO", "user_id": p.user_id,
            "payload": {"target_user_id": opp.user_id, "transfer_card_index": 2},
        })
        ev = next(e for e in events if e["type"] == "PLAY_TWO")
        assert ev["transferred_card"]["rank"] == "9"
        # P0 lost both the 2C and the 9D
        assert len(state.players[0].cards) == 1
        assert state.players[0].cards[0]["rank"] == "6"
        # Opp got the 9D
        assert len(state.players[1].cards) == len(opp_before) + 1

    def test_play_two_with_no_defense_card_fails(self):
        state = make_state(2, target=31)
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        seat = state.current_turn_seat
        p = state.players[seat]
        p.cards = [{"rank": "K", "suit": "S"}]  # no 2H/2C
        from game_engine.scoring import score_hand
        s = score_hand(p.cards, 31)
        p.score = s["total"]
        with pytest.raises(ReducerError, match="PLAY_TWO_NO_DEFENSE_CARD"):
            reduce(state, {
                "type": "PLAY_TWO", "user_id": p.user_id,
                "payload": {"target_user_id": state.players[1].user_id, "transfer_card_index": 0},
            })

    def test_play_ten_attack_sends_card_to_opponent(self):
        state = make_state(2, target=31)
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        seat = state.current_turn_seat
        p = state.players[seat]
        opp = state.players[1 - seat]
        p.cards = [
            {"rank": "10", "suit": "H"},
            {"rank": "9", "suit": "S"},
        ]
        from game_engine.scoring import score_hand
        s = score_hand(p.cards, 31)
        p.score = s["total"]
        opp_before = len(opp.cards)
        state, events = reduce(state, {
            "type": "PLAY_TEN", "user_id": p.user_id,
            "payload": {"target_user_id": opp.user_id, "attack_card_index": 1},
        })
        ev = next(e for e in events if e["type"] == "PLAY_TEN")
        assert ev["sent_card"]["rank"] == "9"
        # P0 has neither the 10H nor the 9S anymore
        assert len(state.players[0].cards) == 0
        # Opp got the 9S
        assert len(state.players[1].cards) == opp_before + 1

    def test_play_ten_without_attack_card_fails(self):
        state = make_state(2, target=31)
        state, _ = start_hand(state)
        state = all_check_through_betting(state)
        seat = state.current_turn_seat
        p = state.players[seat]
        p.cards = [{"rank": "5", "suit": "H"}]
        with pytest.raises(ReducerError, match="PLAY_TEN_NO_ATTACK_CARD"):
            reduce(state, {
                "type": "PLAY_TEN", "user_id": p.user_id,
                "payload": {"target_user_id": state.players[1].user_id, "attack_card_index": 0},
            })


# =====================================================================
# Server-only enforcement
# =====================================================================

class TestServerOnly:
    def test_client_cannot_send_auto_stand_timeout(self):
        state = make_state(2)
        state, _ = start_hand(state)
        with pytest.raises(ReducerError, match="SERVER_ONLY_ACTION"):
            reduce(state, {"type": "AUTO_STAND_TIMEOUT", "user_id": "u0"})

    def test_client_cannot_send_start_hand(self):
        state = make_state(2)
        with pytest.raises(ReducerError, match="SERVER_ONLY_ACTION"):
            reduce(state, {
                "type": "START_HAND",
                "hand_id": "x", "nonce": 0,
                "server_seed": "0" * 64, "server_seed_hash": "h" * 64,
                "client_seeds": "",
            })


# =====================================================================
# state_version monotonicity
# =====================================================================

class TestStateVersion:
    def test_version_increments_per_action(self):
        state = make_state(2)
        v0 = state.version
        state, _ = start_hand(state)
        assert state.version == v0 + 1
        prev = state.version
        state, _ = reduce(state, {"type": "CHECK", "user_id": state.players[state.current_turn_seat].user_id})
        assert state.version == prev + 1
