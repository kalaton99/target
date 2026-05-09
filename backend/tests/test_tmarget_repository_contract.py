from tmarget.models import (
    TmargetLiquidityPool,
    TmargetMarket,
    TmargetMarketRule,
    TmargetPosition,
    TmargetTrade,
)
from tmarget.repository import InMemoryTmargetRepository


def make_market(market_id="m1", slug="market-one", status="draft", category="Demo"):
    rule = TmargetMarketRule(
        market_id=market_id,
        source_url="https://example.test",
        resolution_criteria="Admin resolves from a demo source.",
        invalid_conditions="",
        timezone="UTC",
    )
    pool = TmargetLiquidityPool(
        market_id=market_id,
        yes_pool=100,
        no_pool=100,
        liquidity_parameter=100,
        updated_at=1.0,
    )
    return TmargetMarket(
        id=market_id,
        slug=slug,
        title=f"Market {market_id}",
        description="Repository contract market.",
        category=category,
        status=status,
        outcome_type="binary",
        yes_label="YES",
        no_label="NO",
        close_time="2030-01-01T00:00:00Z",
        resolution_time=None,
        resolved_outcome=None,
        resolver_notes="",
        created_by="admin",
        created_at=1.0,
        updated_at=1.0,
        rule=rule,
        pool=pool,
    )


def make_trade(trade_id, market_id="m1", user_id="u1", outcome="yes"):
    return TmargetTrade(
        id=trade_id,
        user_id=user_id,
        market_id=market_id,
        side="buy",
        outcome=outcome,
        shares=1,
        price=0.5,
        cost=50,
        fee=0,
        status="filled",
        created_at=1.0,
    )


def test_create_and_retrieve_market_by_id_and_slug():
    repo = InMemoryTmargetRepository()
    market = repo.create_market(make_market())
    assert repo.get_market("m1") == market
    assert repo.get_market_by_slug("market-one") == market
    assert repo.get_market("market-one") == market


def test_list_markets_with_optional_status_and_category_filters():
    repo = InMemoryTmargetRepository()
    repo.create_market(make_market("m1", "one", status="open", category="Weather"))
    repo.create_market(make_market("m2", "two", status="draft", category="Sports"))
    assert [market.id for market in repo.list_markets()] == ["m1", "m2"]
    assert [market.id for market in repo.list_markets(status="open")] == ["m1"]
    assert [market.id for market in repo.list_markets(category="Sports")] == ["m2"]


def test_update_market_status_or_fields():
    repo = InMemoryTmargetRepository()
    market = repo.create_market(make_market())
    market.status = "open"
    market.title = "Updated title"
    repo.update_market(market)
    updated = repo.get_market("m1")
    assert updated.status == "open"
    assert updated.title == "Updated title"


def test_create_and_list_trades_in_stable_order():
    repo = InMemoryTmargetRepository()
    first = repo.create_trade(make_trade("t1"))
    second = repo.create_trade(make_trade("t2"))
    assert repo.list_market_trades("m1") == [first, second]
    assert repo.list_market_trades("other") == []


def test_upsert_position_without_duplicating_unique_tuple():
    repo = InMemoryTmargetRepository()
    repo.upsert_position(TmargetPosition(user_id="u1", market_id="m1", outcome="yes", shares=1))
    repo.upsert_position(TmargetPosition(user_id="u1", market_id="m1", outcome="yes", shares=5))
    repo.upsert_position(TmargetPosition(user_id="u1", market_id="m1", outcome="no", shares=2))
    assert len(repo.positions) == 2
    assert repo.get_position("u1", "m1", "yes").shares == 5


def test_retrieve_user_and_market_positions():
    repo = InMemoryTmargetRepository()
    yes = TmargetPosition(user_id="u1", market_id="m1", outcome="yes", shares=1)
    no = TmargetPosition(user_id="u2", market_id="m1", outcome="no", shares=2)
    other = TmargetPosition(user_id="u1", market_id="m2", outcome="yes", shares=3)
    repo.upsert_position(yes)
    repo.upsert_position(no)
    repo.upsert_position(other)
    assert repo.get_user_positions("u1") == [yes, other]
    assert repo.list_market_positions("m1") == [yes, no]
    assert repo.list_market_positions("m1", "u2") == [no]


def test_get_and_update_liquidity_pool():
    repo = InMemoryTmargetRepository()
    market = repo.create_market(make_market())
    assert repo.get_pool(market.id).yes_pool == 100
    updated = TmargetLiquidityPool(
        market_id=market.id,
        yes_pool=125,
        no_pool=75,
        liquidity_parameter=100,
        updated_at=2.0,
    )
    repo.update_pool(market.id, updated)
    assert repo.get_pool(market.id) == updated


def test_record_settlement_idempotency_key_once():
    repo = InMemoryTmargetRepository()
    first = repo.record_settlement("m1", "u1", "yes", 100, "settlement-key")
    second = repo.record_settlement("m1", "u1", "yes", 100, "settlement-key")
    assert repo.has_settlement("settlement-key")
    assert first == second
    assert len(repo.settlements) == 1


def test_record_refund_idempotency_key_once():
    repo = InMemoryTmargetRepository()
    first = repo.record_refund("m1", "u1", "yes", 50, "refund-key")
    second = repo.record_refund("m1", "u1", "yes", 50, "refund-key")
    assert repo.has_refund("refund-key")
    assert first == second
    assert len(repo.refunds) == 1


def test_record_and_list_admin_actions():
    repo = InMemoryTmargetRepository()
    repo.record_admin_action("open_market", "m1", "admin", {"notes": "demo"})
    actions = repo.list_admin_actions()
    assert actions[0]["id"] == "tm_admin_1"
    assert actions[0]["admin_user_id"] == "admin"
    assert actions[0]["action"] == "open_market"
    actions[0]["action"] = "mutated"
    assert repo.list_admin_actions()[0]["action"] == "open_market"


def test_record_and_list_market_status_history():
    repo = InMemoryTmargetRepository()
    repo.record_status_history(
        market_id="m1",
        from_status="draft",
        to_status="open",
        changed_by="admin",
        reason="demo_open",
    )
    repo.record_status_history(
        market_id="m2",
        from_status="draft",
        to_status="cancelled",
        changed_by="admin",
        reason="demo_cancel",
    )
    history = repo.list_status_history("m1")
    assert len(history) == 1
    assert history[0]["from_status"] == "draft"
    assert history[0]["to_status"] == "open"
    assert history[0]["changed_by"] == "admin"
