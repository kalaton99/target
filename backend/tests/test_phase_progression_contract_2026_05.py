"""Phase-progression contract tests — multi-round skip rules.

Locks in the deterministic, reducer-level behaviour the live
`test_phase11_validation.py::test_f3_f4_f11_canonical_flow_with_bot`
test asserts at the broadcast layer. Pure-Python, no network, no
flakes.

Contract under test (reducer `_enter_betting_round`, line ~232):

    BETTING_R{n} entry with len(in_hand) <= 1  →  short-circuit to
                                                  SHOWDOWN.

When a JOKER hits during DRAW_2 in a hand with only 2 seated players,
the affected player is disqualified (in_hand=False), collapsing alive
count to 1, which must skip BETTING_R3 entirely. The previous live
test asserted a fixed 5-phase progression and flaked at the
JOKER-draw rate.

Wording note (per GAME_RULES_LOCKED.md §2): there is NO 2-seat table
type. The test scenarios below use `n_players=2` to mean "a 4-seat
(target=30) table with 2 humans seated" — the minimum legal start
for the 4-seat tier. 5-seat tables (target 75/100) require ≥3
seated to start.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game_engine.reducer import reduce  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402


def _make_state(n=2, target=30):
    s = GameState(table_id="phase_skip_t", target_score=target, stake=100)
    s.players = [
        PlayerState(seat_index=i, user_id=f"u{i}", username=f"P{i}",
                    balance_at_start=10000)
        for i in range(n)
    ]
    return s


def _start(state):
    state, _ = reduce(state, {
        "type": "START_HAND", "source": "SERVER",
        "hand_id": "h_phase", "nonce": 0,
        "server_seed": "0" * 64, "server_seed_hash": "h" * 64,
        "client_seeds": "",
    })
    return state


def _all_check(state):
    while state.phase in ("BETTING_R1", "BETTING_R2", "BETTING_R3"):
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "CHECK", "user_id": user})
    return state


def _all_stand(state):
    while state.phase in ("DRAW", "DRAW_1", "DRAW_2"):
        seat = state.current_turn_seat
        if seat is None:
            break
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "STAND", "user_id": user})
    return state


# =====================================================================
# Mainline canonical progression (no DQ, no fold)
# =====================================================================

class TestCanonical5PhaseProgression:
    def test_two_player_no_dq_walks_full_5_phases(self):
        """With both players still in_hand at every transition, the
        5-phase canonical progression must be observed in order:
            BETTING_R1 → DRAW_1 → BETTING_R2 → DRAW_2 → BETTING_R3 →
            SHOWDOWN/PAYOUT.
        """
        state = _make_state(2, target=30)
        state = _start(state)
        seen = [state.phase]

        def step(s):
            seen.append(s.phase)

        state = _all_check(state)
        step(state)        # BETTING_R1 → DRAW_1
        state = _all_stand(state)
        step(state)         # DRAW_1 → BETTING_R2
        state = _all_check(state)
        step(state)         # BETTING_R2 → DRAW_2
        state = _all_stand(state)
        step(state)         # DRAW_2 → BETTING_R3
        state = _all_check(state)
        step(state)         # BETTING_R3 → SHOWDOWN/PAYOUT

        # The five required transition-end phases must appear in order.
        # `seen[0]` is BETTING_R1 (post-START_HAND), the rest are after
        # each helper call.
        assert seen[0] == "BETTING_R1"
        assert seen[1] == "DRAW_1"
        assert seen[2] == "BETTING_R2"
        assert seen[3] == "DRAW_2"
        assert seen[4] == "BETTING_R3"
        assert seen[5] in ("SHOWDOWN", "PAYOUT")


# =====================================================================
# JOKER mid-DRAW_2 → DQ → BETTING_R3 skip
# =====================================================================

class TestJokerCollapsesProgression:
    def test_joker_in_draw_2_skips_betting_r3(self):
        """Inject a JOKER on top of the deck right before DRAW_2's first
        HIT, so the very next draw disqualifies that player. After the
        other player STANDs, `_enter_betting_round(3)` sees
        `len(in_hand)==1` and short-circuits to SHOWDOWN — BETTING_R3
        must NEVER appear.

        Scenario uses 2 seated players on a 4-seat (target=30) table —
        the minimum legal start for the 4-seat tier per
        GAME_RULES_LOCKED.md §2. There is no 2-seat table type.
        """
        state = _make_state(2, target=30)
        state = _start(state)
        # Fast-forward to DRAW_1.
        state = _all_check(state)
        assert state.phase == "DRAW_1"
        # Both stand in DRAW_1 → BETTING_R2.
        state = _all_stand(state)
        assert state.phase == "BETTING_R2"
        # Both check through BETTING_R2 → DRAW_2.
        state = _all_check(state)
        assert state.phase == "DRAW_2"

        # In DRAW_2: ensure both players are eligible to draw (clear
        # any sticky stand from DRAW_1 — the reducer carries it across
        # rounds by design, but for THIS contract test we want both
        # to actively act in DRAW_2 so the JOKER path is exercised).
        for p in state.players:
            p.stood = False

        # Inject a JOKER as the next card to be drawn so the very next
        # HIT disqualifies the drawer.
        state.deck.insert(0, {"rank": "JOKER", "suit": "*", "code": "JK"})

        # Whoever is on turn HITs → draws the JOKER → DQ.
        seat = state.current_turn_seat
        assert seat is not None
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "HIT", "user_id": user})
        assert state.players[seat].disqualified is True
        assert state.players[seat].in_hand is False

        # The remaining player STANDs → DRAW_2 ends → reducer enters
        # BETTING_R3 entry, sees `len(in_hand)==1`, jumps to SHOWDOWN.
        seen_after_dq = [state.phase]
        while state.phase in ("DRAW", "DRAW_1", "DRAW_2",
                              "BETTING_R1", "BETTING_R2", "BETTING_R3"):
            cur = state.current_turn_seat
            if cur is None:
                break
            user = state.players[cur].user_id
            # Use STAND in draws, CHECK in betting.
            act = "STAND" if state.phase.startswith("DRAW") else "CHECK"
            state, _ = reduce(state, {"type": act, "user_id": user})
            seen_after_dq.append(state.phase)

        # Contract: BETTING_R3 must NEVER appear in this trace.
        assert "BETTING_R3" not in seen_after_dq, (
            f"reducer entered BETTING_R3 with only 1 alive player; "
            f"seen={seen_after_dq}"
        )
        # And we must reach SHOWDOWN/PAYOUT cleanly.
        assert state.phase in ("SHOWDOWN", "PAYOUT", "ENDED"), (
            f"hand stranded at {state.phase}"
        )

    def test_joker_in_draw_1_skips_directly_to_showdown(self):
        """JOKER drawn in DRAW_1 with only 2 seated players → DQ → at
        end of DRAW_1, `_enter_betting_round(2)` sees alive=1 →
        SHOWDOWN. Neither BETTING_R2, DRAW_2 nor BETTING_R3 must be
        entered.

        Scenario: 4-seat (target=30) table with 2 humans seated.
        """
        state = _make_state(2, target=30)
        state = _start(state)
        state = _all_check(state)
        assert state.phase == "DRAW_1"

        state.deck.insert(0, {"rank": "JOKER", "suit": "*", "code": "JK"})
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "HIT", "user_id": user})
        assert state.players[seat].disqualified is True

        seen = [state.phase]
        while state.phase in ("DRAW", "DRAW_1", "DRAW_2",
                              "BETTING_R1", "BETTING_R2", "BETTING_R3"):
            cur = state.current_turn_seat
            if cur is None:
                break
            user = state.players[cur].user_id
            act = "STAND" if state.phase.startswith("DRAW") else "CHECK"
            state, _ = reduce(state, {"type": act, "user_id": user})
            seen.append(state.phase)

        for forbidden in ("BETTING_R2", "DRAW_2", "BETTING_R3"):
            assert forbidden not in seen, (
                f"reducer should have collapsed past {forbidden}; saw {seen}"
            )
        assert state.phase in ("SHOWDOWN", "PAYOUT", "ENDED")


# =====================================================================
# Fold mid-BETTING also collapses progression
# =====================================================================

class TestFoldCollapsesProgression:
    def test_fold_in_betting_r2_skips_draw_2_and_r3(self):
        """A FOLD in BETTING_R2 with only 2 seated players reduces alive
        count to 1; the reducer skips DRAW_2 and BETTING_R3, going
        straight to SHOWDOWN.

        Scenario: 4-seat (target=30) table with 2 humans seated.
        """
        state = _make_state(2, target=30)
        state = _start(state)
        state = _all_check(state)        # → DRAW_1
        state = _all_stand(state)         # → BETTING_R2
        assert state.phase == "BETTING_R2"

        # Whoever is on turn FOLDs.
        seat = state.current_turn_seat
        user = state.players[seat].user_id
        state, _ = reduce(state, {"type": "FOLD", "user_id": user})

        # Reducer must have collapsed straight to SHOWDOWN/PAYOUT.
        assert state.phase in ("SHOWDOWN", "PAYOUT"), (
            f"FOLD with 1 remaining alive must skip to SHOWDOWN; "
            f"phase={state.phase}"
        )
