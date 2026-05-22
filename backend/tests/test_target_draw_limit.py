import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.constants import MAX_DRAWS_PER_TURN
from game_engine.reducer import reduce
from game_engine.types import GameState, PlayerState


def _card(rank="A", suit="S"):
    return {"rank": rank, "suit": suit}


def test_target_player_cannot_draw_more_than_five_cards_in_one_turn():
    state = GameState(table_id="draw_limit", target_score=61, stake=0)
    state.phase = "DRAW_1"
    state.draw_active_count = 2
    state.current_turn_seat = 0
    state.players = [
        PlayerState(seat_index=0, user_id="u0", username="P0", balance_at_start=1000),
        PlayerState(seat_index=1, user_id="u1", username="P1", balance_at_start=1000),
    ]
    state.players[0].cards = [_card("2", "S"), _card("3", "H")]
    state.deck = [_card("A", suit) for suit in ("S", "H", "D", "C")]

    seen_limit_event = False
    for _ in range(MAX_DRAWS_PER_TURN - len(state.players[0].cards)):
        state, events = reduce(state, {"type": "HIT", "user_id": "u0"})
        seen_limit_event = seen_limit_event or any(event.get("type") == "DRAW_LIMIT_REACHED" for event in events)

    assert len(state.players[0].cards) == MAX_DRAWS_PER_TURN
    assert state.players[0].stood is True
    assert state.players[0].draws_this_turn == 3
    assert seen_limit_event
    assert state.last_action_summary["action"] == "DRAW_LIMIT_REACHED"
    assert state.phase != "DRAW_1" or state.current_turn_seat != 0


def test_target_sixth_card_is_blocked_without_drawing():
    state = GameState(table_id="draw_limit_sixth", target_score=61, stake=0)
    state.phase = "DRAW_1"
    state.draw_active_count = 2
    state.current_turn_seat = 0
    state.players = [
        PlayerState(seat_index=0, user_id="u0", username="P0", balance_at_start=1000),
        PlayerState(seat_index=1, user_id="u1", username="P1", balance_at_start=1000),
    ]
    state.players[0].cards = [_card(str(rank), "S") for rank in range(1, MAX_DRAWS_PER_TURN + 1)]
    state.deck = [_card("K", "H")]

    state, events = reduce(state, {"type": "HIT", "user_id": "u0"})

    assert len(state.players[0].cards) == MAX_DRAWS_PER_TURN
    assert state.deck == [_card("K", "H")]
    assert state.players[0].stood is True
    assert any(event.get("type") == "DRAW_LIMIT_REACHED" for event in events)
