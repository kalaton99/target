from core.constants import BOT_COUNT_MAX, max_bots_for_target


def test_target_local_demo_bot_capacity_matches_table_seats():
    assert BOT_COUNT_MAX == 4
    assert max_bots_for_target(30) == 3
    assert max_bots_for_target(50) == 3
    assert max_bots_for_target(75) == 4
    assert max_bots_for_target(100) == 4
