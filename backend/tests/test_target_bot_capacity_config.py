from core.constants import BOT_COUNT_MAX, TABLE_SEATS_BY_TARGET, max_bots_for_target


def test_target_local_demo_bot_capacity_matches_table_seats():
    assert BOT_COUNT_MAX == 4
    assert TABLE_SEATS_BY_TARGET[31] == 4
    assert TABLE_SEATS_BY_TARGET[41] == 4
    assert TABLE_SEATS_BY_TARGET[51] == 5
    assert TABLE_SEATS_BY_TARGET[61] == 5
    assert max_bots_for_target(31) == 3
    assert max_bots_for_target(41) == 3
    assert max_bots_for_target(51) == 4
    assert max_bots_for_target(61) == 4
