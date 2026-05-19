import copy
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "axwins_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("RNG_ENCRYPTION_KEY", "test-rng-key")
os.environ.setdefault("TMARGET_DEMO_ADMIN_ENABLED", "1")

from core.security import current_user_id
from diceget.router import build_diceget_router
from diceget.service import DicegetService
from flipget.router import build_flipget_router
from flipget.service import FlipgetService
from tmarget.admin_guard import demo_admin_guard
from tmarget.router import build_tmarget_router
from tmarget.service import TmargetService


class FakeResult:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        doc_id = doc.get("id")
        if doc_id and any(existing.get("id") == doc_id for existing in self.docs):
            raise DuplicateKeyError("duplicate id")
        self.docs.append(copy.deepcopy(doc))
        return FakeResult()

    async def insert_many(self, docs):
        for doc in docs:
            await self.insert_one(doc)
        return FakeResult()

    async def find_one(self, filt, projection=None):
        for doc in self.docs:
            if _matches(doc, filt):
                out = copy.deepcopy(doc)
                if projection and projection.get("_id") == 0:
                    out.pop("_id", None)
                return out
        return None

    async def find_one_and_update(self, filt, update, return_document=None, projection=None):
        for idx, doc in enumerate(self.docs):
            if not _matches(doc, filt):
                continue
            _apply_update(doc, update)
            self.docs[idx] = doc
            out = copy.deepcopy(doc)
            if projection and projection.get("_id") == 0:
                out.pop("_id", None)
            return out
        return None

    async def update_one(self, filt, update):
        for doc in self.docs:
            if _matches(doc, filt):
                _apply_update(doc, update)
                return FakeResult()
        return FakeResult(matched_count=0)

    async def update_many(self, filt, update):
        matched = 0
        for doc in self.docs:
            if _matches(doc, filt):
                _apply_update(doc, update)
                matched += 1
        return FakeResult(matched)


class FakeDb:
    def __init__(self):
        self.wallets = FakeCollection()
        self.transactions = FakeCollection()
        self.idempotency_keys = FakeCollection()
        self.journals = FakeCollection()
        self.audit_log = FakeCollection()

    def __getitem__(self, key):
        if key == "wallets":
            return self.wallets
        if key == "transactions":
            return self.transactions
        if key == "idempotency_keys":
            return self.idempotency_keys
        if key == "journals":
            return self.journals
        if key == "audit_log":
            return self.audit_log
        raise KeyError(key)


def _wallet_doc(user_id, balance=1000):
    return {
        "id": f"w_{user_id}",
        "user_id": user_id,
        "balance": balance,
        "gems": 0,
        "locked": 0,
        "locked_balance": 0,
        "version": 0,
        "last_journal_id": None,
        "updated_at": "2026-05-18T00:00:00Z",
    }


def _matches(doc, filt):
    for key, expected in filt.items():
        if key == "$or":
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and not (actual is not None and actual >= expected["$gte"]):
                return False
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$nin" in expected and actual in expected["$nin"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _apply_update(doc, update):
    for key, amount in update.get("$inc", {}).items():
        doc[key] = doc.get(key, 0) + amount
    for key, value in update.get("$set", {}).items():
        doc[key] = value


def _client(monkeypatch):
    fake_db = FakeDb()
    fake_db.wallets.docs.extend([
        _wallet_doc("u1"),
        _wallet_doc("u2"),
        _wallet_doc("intruder"),
    ])
    monkeypatch.setattr("diceget.router.core_db.db", fake_db)
    monkeypatch.setattr("flipget.router.core_db.db", fake_db)
    monkeypatch.setattr("tmarget.router.core_db.db", fake_db)

    current = {"user_id": "u1"}
    app = FastAPI()
    app.dependency_overrides[current_user_id] = lambda: current["user_id"]
    app.dependency_overrides[demo_admin_guard] = lambda: None
    app.include_router(build_diceget_router(DicegetService(dice_rng=lambda: 2)), prefix="/api")
    app.include_router(build_flipget_router(FlipgetService(coin_rng=lambda: "heads")), prefix="/api")
    app.include_router(build_tmarget_router(TmargetService()), prefix="/api")
    return TestClient(app), current


def test_diceget_api_loop_roll_hold_and_forfeit_stays_diceget(monkeypatch):
    client, current = _client(monkeypatch)

    created = client.post("/api/diceget/tables", json={"target_score": 30, "stake": 100}).json()
    table_id = created["table_id"]
    for _ in range(3):
        response = client.post(f"/api/diceget/tables/{table_id}/add-bot", json={"profile": "safe"})
        assert response.status_code == 200
    started = client.post(f"/api/diceget/tables/{table_id}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "active"

    rolled = client.post(f"/api/diceget/tables/{table_id}/roll")
    assert rolled.status_code == 200
    assert rolled.json()["rolls"][-1]["total"] == 4
    assert rolled.json()["seats"][0]["score"] == 4

    held = client.post(f"/api/diceget/tables/{table_id}/hold")
    assert held.status_code == 200
    assert held.json()["seats"][0]["status"] == "held"

    second = client.post("/api/diceget/tables", json={"target_score": 30, "stake": 100}).json()
    second_id = second["table_id"]
    for _ in range(3):
        client.post(f"/api/diceget/tables/{second_id}/add-bot", json={"profile": "safe"})
    client.post(f"/api/diceget/tables/{second_id}/start")
    current["user_id"] = "intruder"
    blocked = client.post(f"/api/diceget/tables/{second_id}/roll")
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "NOT_YOUR_TURN"

    current["user_id"] = "u1"
    forfeited = client.post(f"/api/diceget/tables/{second_id}/forfeit")
    assert forfeited.status_code == 200
    assert forfeited.json()["seats"][0]["status"] == "forfeited"


def test_flipget_api_loop_blocks_one_user_then_completes_two_user_flip(monkeypatch):
    client, current = _client(monkeypatch)

    created = client.post("/api/flipget/tables", json={"stake_amount": 100}).json()
    table_id = created["table_id"]
    client.post(f"/api/flipget/tables/{table_id}/choose-side", json={"side": "heads"})
    client.post(f"/api/flipget/tables/{table_id}/ready")
    blocked = client.post(f"/api/flipget/tables/{table_id}/flip")
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "REQUIRES_EXACTLY_2_SEATS"

    demo = client.post(f"/api/flipget/tables/{table_id}/add-demo-opponent", json={"username": "Demo Opponent"})
    assert demo.status_code == 200
    assert demo.json()["status"] == "ready"
    assert {seat["side"] for seat in demo.json()["seats"]} == {"heads", "tails"}
    assert all(seat["ready"] for seat in demo.json()["seats"])

    flipped = client.post(f"/api/flipget/tables/{table_id}/flip")
    assert flipped.status_code == 200
    payload = flipped.json()
    assert payload["status"] == "settled"
    assert payload["round"]["result"] == "heads"
    assert payload["round"]["winner_user_id"] == "u1"


def test_tmarget_api_loop_yes_no_positions_and_market_payload(monkeypatch):
    client, current = _client(monkeypatch)

    market = client.post(
        "/api/tmarget/admin/markets",
        json={
            "title": "API loop market",
            "description": "Internal demo-credit API loop market.",
            "category": "Audit",
            "close_time": "2030-01-01T00:00:00Z",
            "resolution_criteria": "Audit-only criterion.",
            "initial_liquidity": 100,
        },
    ).json()
    market_id = market["id"]
    assert client.post(f"/api/tmarget/admin/markets/{market_id}/open").status_code == 200

    yes = client.post(f"/api/tmarget/markets/{market_id}/buy", json={"outcome": "yes", "shares": 1})
    assert yes.status_code == 200
    assert yes.json()["trade"]["outcome"] == "yes"

    no = client.post(f"/api/tmarget/markets/{market_id}/buy", json={"outcome": "no", "shares": 1})
    assert no.status_code == 200
    assert no.json()["trade"]["outcome"] == "no"

    positions = client.get(f"/api/tmarget/markets/{market_id}/positions").json()["positions"]
    outcomes = {position["outcome"]: position["shares"] for position in positions}
    assert outcomes == {"yes": 1, "no": 1}
    trades = client.get(f"/api/tmarget/markets/{market_id}/trades").json()["trades"]
    assert [trade["outcome"] for trade in trades] == ["yes", "no"]
    assert client.get(f"/api/tmarget/markets/{market['slug']}").json()["volume"] > market["volume"]

    current["user_id"] = "u2"
    assert client.get("/api/tmarget/me/positions").json()["positions"] == []
