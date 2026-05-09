import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017/axwins-test")
os.environ.setdefault("DB_NAME", "axwins_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("RNG_ENCRYPTION_KEY", "0" * 32)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.security import current_user_id
from tmarget.models import TmargetLiquidityPool, TmargetPosition, TmargetTrade
from tmarget.repository import InMemoryTmargetRepository
from tmarget.router import build_tmarget_router
from tmarget.service import TmargetService


def market_payload():
    return {
        "title": "Will the repository demo resolve YES?",
        "description": "Repository test market.",
        "category": "Demo",
        "close_time": "2030-01-01T00:00:00Z",
        "resolution_criteria": "Admin resolves from a demo source.",
        "source_url": "https://example.test",
        "initial_liquidity": 100,
    }


def make_service():
    repo = InMemoryTmargetRepository()
    service = TmargetService(repository=repo)
    return service, repo


def test_repository_create_retrieve_and_list_market():
    service, repo = make_service()
    market = service.create_market(created_by="admin", **market_payload())
    assert repo.get_market(market.id).id == market.id
    assert repo.get_market(market.slug).id == market.id
    assert [item.id for item in repo.list_markets()] == [market.id]


def test_repository_create_and_list_trades():
    _, repo = make_service()
    trade = TmargetTrade(
        id="trade_1",
        user_id="u1",
        market_id="m1",
        side="buy",
        outcome="yes",
        shares=2,
        price=0.5,
        cost=100,
        fee=0,
        status="filled",
        created_at=1.0,
    )
    repo.create_trade(trade)
    assert repo.list_market_trades("m1") == [trade]
    assert repo.list_market_trades("other") == []


def test_repository_upsert_and_retrieve_user_positions():
    _, repo = make_service()
    position = TmargetPosition(user_id="u1", market_id="m1", outcome="yes", shares=3, avg_price=0.5)
    repo.upsert_position(position)
    assert repo.get_position("u1", "m1", "yes").shares == 3
    assert repo.get_user_positions("u1") == [position]
    assert repo.list_market_positions("m1", "u1") == [position]


def test_repository_create_and_update_pool_state():
    service, repo = make_service()
    market = service.create_market(created_by="admin", **market_payload())
    pool = repo.get_pool(market.id)
    assert pool.yes_pool == 100
    updated = TmargetLiquidityPool(
        market_id=market.id,
        yes_pool=120,
        no_pool=90,
        liquidity_parameter=100,
        updated_at=2.0,
    )
    repo.update_pool(market.id, updated)
    assert repo.get_pool(market.id).yes_pool == 120
    assert repo.get_pool(market.id).no_pool == 90


def test_repository_records_settlements_refunds_and_admin_actions():
    _, repo = make_service()
    repo.record_settlement("m1", "u1", "yes", 200, "settle-key")
    repo.record_refund("m1", "u2", "no", 100, "refund-key")
    repo.record_admin_action("open_market", "m1", "admin")
    assert repo.settlements[0]["idempotency_key"] == "settle-key"
    assert repo.refunds[0]["amount"] == 100
    assert repo.list_admin_actions()[0]["action"] == "open_market"


def build_test_client():
    service, _ = make_service()
    app = FastAPI()
    app.dependency_overrides[current_user_id] = lambda: "admin-user"
    app.include_router(build_tmarget_router(service))
    return TestClient(app)


def test_admin_endpoints_require_demo_admin_guard():
    client = build_test_client()
    response = client.post("/tmarget/admin/markets", json=market_payload())
    assert response.status_code == 403
    assert response.json()["detail"] == "TMARGET_DEMO_ADMIN_ONLY"


def test_admin_endpoints_succeed_with_demo_admin_header():
    client = build_test_client()
    response = client.post(
        "/tmarget/admin/markets",
        json=market_payload(),
        headers={"X-Axwins-Demo-Admin": "true"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == market_payload()["title"]
    opened = client.post(
        f"/tmarget/admin/markets/{data['id']}/open",
        headers={"X-Axwins-Demo-Admin": "true"},
    )
    assert opened.status_code == 200
    assert opened.json()["status"] == "open"


def test_public_market_endpoints_do_not_require_demo_admin_header():
    client = build_test_client()
    response = client.get("/tmarget/markets")
    assert response.status_code == 200
    assert response.json()["markets"] == []
