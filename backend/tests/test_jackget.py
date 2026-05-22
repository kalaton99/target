import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jackget.models import JACKGET_SPINS_PER_PLAYER
from jackget.service import JackgetError, JackgetService, score_reels


def test_jackget_score_examples_are_deterministic():
    assert score_reels(["Seven", "Seven", "Seven"]) == 100
    assert score_reels(["Diamond", "Diamond", "Diamond"]) == 90
    assert score_reels(["Crown", "Crown", "Crown"]) == 80
    assert score_reels(["7", "7", "7"]) == 70
    assert score_reels(["Bell", "Bell", "Cherry"]) == 15
    assert score_reels(["1", "Star", "4"]) == 10


def test_jackget_table_min_max_and_demo_opponents():
    service = JackgetService(reel_rng=lambda: "Cherry")
    with pytest.raises(JackgetError) as too_small:
        service.create_table(creator_user_id="u1", max_players=1)
    assert too_small.value.code == "INVALID_TABLE_SIZE"
    with pytest.raises(JackgetError) as too_large:
        service.create_table(creator_user_id="u1", max_players=5)
    assert too_large.value.code == "INVALID_TABLE_SIZE"

    table = service.create_table(creator_user_id="u1", username="Player", max_players=4)
    assert table.status == "waiting"
    with pytest.raises(JackgetError) as blocked:
        service.start_table(table_id=table.id, user_id="u1")
    assert blocked.value.code == "REQUIRES_MINIMUM_2_PLAYERS"

    table = service.add_demo_opponents(table_id=table.id)
    assert len(table.seats) == 4
    assert sum(1 for seat in table.seats if seat.is_demo) == 3
    assert table.status == "ready"


def test_jackget_turn_order_spin_limit_and_settlement():
    sequence = iter(["Seven", "Seven", "Seven"] * 12)
    service = JackgetService(reel_rng=lambda: next(sequence))
    table = service.create_table(creator_user_id="u1", username="Player", max_players=2)
    table = service.add_demo_opponents(table_id=table.id)
    table = service.start_table(table_id=table.id, user_id="u1")
    assert table.current_turn_user_id == "u1"

    table = service.spin(table_id=table.id, user_id="u1")
    assert len(table.seats[0].spins) == 1
    assert len(table.seats[1].spins) == 1
    assert table.current_turn_user_id == "u1"

    for _ in range(JACKGET_SPINS_PER_PLAYER - 1):
        table = service.spin(table_id=table.id, user_id="u1")
    assert len(table.seats[0].spins) == JACKGET_SPINS_PER_PLAYER
    assert all(len(seat.spins) == JACKGET_SPINS_PER_PLAYER for seat in table.seats)
    assert table.status == "settled"
    assert table.current_turn_user_id is None
    with pytest.raises(JackgetError) as blocked:
        service.spin(table_id=table.id, user_id="u1")
    assert blocked.value.code == "TABLE_NOT_ACTIVE"

    assert len(table.winners) == 2
    assert all(seat.total_score == 300 for seat in table.seats)


def test_jackget_three_player_demo_turns_auto_resolve_until_human_turn():
    sequence = iter(["Cherry", "Cherry", "Cherry"] * 18)
    service = JackgetService(reel_rng=lambda: next(sequence))
    table = service.create_table(creator_user_id="u1", username="Player", max_players=3)
    table = service.add_demo_opponents(table_id=table.id)
    table = service.start_table(table_id=table.id, user_id="u1")

    table = service.spin(table_id=table.id, user_id="u1")

    assert [len(seat.spins) for seat in table.seats] == [1, 1, 1]
    assert table.current_turn_user_id == "u1"
