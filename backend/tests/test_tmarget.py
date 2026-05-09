import copy

import pytest
from pymongo.errors import DuplicateKeyError

from ledger.service import LedgerService
from tmarget.service import TmargetError, TmargetService


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


@pytest.fixture
async def ledger():
    wallets = FakeCollection()
    transactions = FakeCollection()
    idem = FakeCollection()
    journals = FakeCollection()
    audit = FakeCollection()
    service = LedgerService(wallets, transactions, idem, journals, audit_col=audit)
    for user_id in ("u1", "u2", "u3"):
        await service.open_wallet(user_id, opening_balance=1000)
    await service.open_wallet("low_balance", opening_balance=10)
    return service, wallets, transactions


def make_market(service=None):
    service = service or TmargetService()
    market = service.create_market(
        title="Will the demo market resolve YES?",
        description="Demo market for service tests.",
        category="Demo",
        close_time="2030-01-01T00:00:00Z",
        resolution_criteria="Admin resolver checks the demo source.",
        source_url="https://example.test",
        initial_liquidity=100,
        created_by="admin",
    )
    return service, market


def open_market(service=None):
    service, market = make_market(service)
    service.open_market(market.id)
    return service, market


def assert_error(code, fn, *args, **kwargs):
    with pytest.raises(TmargetError) as err:
        fn(*args, **kwargs)
    assert err.value.code == code


async def assert_async_error(code, coro):
    with pytest.raises(TmargetError) as err:
        await coro
    assert err.value.code == code


def test_create_binary_market_and_reject_missing_required_fields():
    service, market = make_market()
    payload = service.market_payload(market)
    assert payload["outcome_type"] == "binary"
    assert payload["status"] == "draft"
    assert payload["yes_price"] == 0.5
    assert payload["no_price"] == 0.5
    assert_error(
        "TITLE_REQUIRED",
        service.create_market,
        title="",
        description="",
        category="Demo",
        close_time="2030-01-01T00:00:00Z",
        resolution_criteria="Criteria",
        created_by="admin",
    )
    assert_error(
        "RESOLUTION_CRITERIA_REQUIRED",
        service.create_market,
        title="Missing criteria",
        description="",
        category="Demo",
        close_time="2030-01-01T00:00:00Z",
        resolution_criteria="",
        created_by="admin",
    )
    assert_error(
        "VALID_CLOSE_TIME_REQUIRED",
        service.create_market,
        title="Missing close time",
        description="",
        category="Demo",
        close_time="",
        resolution_criteria="Criteria",
        created_by="admin",
    )
    assert_error(
        "VALID_CLOSE_TIME_REQUIRED",
        service.create_market,
        title="Invalid close time",
        description="",
        category="Demo",
        close_time="invalid-date",
        resolution_criteria="Criteria",
        created_by="admin",
    )


def test_reject_non_binary_or_missing_liquidity():
    service = TmargetService()
    kwargs = {
        "title": "Non-binary",
        "description": "",
        "category": "Demo",
        "close_time": "2030-01-01T00:00:00Z",
        "resolution_criteria": "Criteria",
        "created_by": "admin",
    }
    assert_error("ONLY_BINARY_MARKETS_SUPPORTED", service.create_market, **kwargs, outcome_type="multi")
    assert_error("INITIAL_LIQUIDITY_REQUIRED", service.create_market, **kwargs, initial_liquidity=0)


def test_market_lifecycle_open_pause_close_cancel():
    service, market = make_market()
    assert service.open_market(market.id).status == "open"
    assert service.pause_market(market.id).status == "paused"
    assert service.open_market(market.id).status == "open"
    assert service.close_market(market.id).status == "closed"


async def test_cancel_market_sets_cancelled_and_refunds_positions_once(ledger):
    ledger_service, wallets, transactions = ledger
    service, market = open_market()
    await service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=2, ledger=ledger_service)
    wallet_after_buy = await wallets.find_one({"user_id": "u1"})
    assert wallet_after_buy["balance"] == 900
    await service.cancel_market(market.id, ledger_service)
    await service.cancel_market(market.id, ledger_service)
    wallet_after_cancel = await wallets.find_one({"user_id": "u1"})
    assert wallet_after_cancel["balance"] == 1000
    assert len(transactions.docs) == 4


async def test_cannot_trade_unless_market_open(ledger):
    ledger_service, _, _ = ledger
    service, market = make_market()
    await assert_async_error(
        "MARKET_NOT_OPEN",
        service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=1, ledger=ledger_service),
    )
    service.open_market(market.id)
    service.pause_market(market.id)
    await assert_async_error(
        "MARKET_NOT_OPEN",
        service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=1, ledger=ledger_service),
    )
    service.close_market(market.id)
    await assert_async_error(
        "MARKET_NOT_OPEN",
        service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=1, ledger=ledger_service),
    )
    await service.resolve_market(market_id=market.id, outcome="yes", resolver_notes="Resolved", ledger=ledger_service)
    await assert_async_error(
        "MARKET_NOT_OPEN",
        service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=1, ledger=ledger_service),
    )
    service2, cancelled = make_market()
    await service2.cancel_market(cancelled.id, ledger_service)
    await assert_async_error(
        "MARKET_NOT_OPEN",
        service2.buy(market_id=cancelled.id, user_id="u1", outcome="yes", shares=1, ledger=ledger_service),
    )


async def test_buy_yes_and_no_debit_balance_and_create_positions(ledger):
    ledger_service, wallets, _ = ledger
    service, market = open_market()
    yes = await service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=2, ledger=ledger_service)
    no = await service.buy(market_id=market.id, user_id="u2", outcome="no", shares=2, ledger=ledger_service)
    assert yes.outcome == "yes"
    assert no.outcome == "no"
    assert service._position("u1", market.id, "yes").shares == 2
    assert service._position("u2", market.id, "no").shares == 2
    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] < 1000


async def test_insufficient_balance_rejected(ledger):
    ledger_service, wallets, _ = ledger
    service, market = open_market()
    await assert_async_error(
        "INSUFFICIENT_BALANCE",
        service.buy(market_id=market.id, user_id="low_balance", outcome="yes", shares=1, ledger=ledger_service),
    )
    wallet = await wallets.find_one({"user_id": "low_balance"})
    assert wallet["balance"] == 10


async def test_sell_yes_and_no_credit_balance_and_reduce_positions(ledger):
    ledger_service, wallets, _ = ledger
    service, market = open_market()
    await service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=4, ledger=ledger_service)
    await service.buy(market_id=market.id, user_id="u2", outcome="no", shares=4, ledger=ledger_service)
    before_u1 = (await wallets.find_one({"user_id": "u1"}))["balance"]
    before_u2 = (await wallets.find_one({"user_id": "u2"}))["balance"]
    await service.sell(market_id=market.id, user_id="u1", outcome="yes", shares=2, ledger=ledger_service)
    await service.sell(market_id=market.id, user_id="u2", outcome="no", shares=2, ledger=ledger_service)
    assert (await wallets.find_one({"user_id": "u1"}))["balance"] > before_u1
    assert (await wallets.find_one({"user_id": "u2"}))["balance"] > before_u2
    assert service._position("u1", market.id, "yes").shares == 2
    assert service._position("u2", market.id, "no").shares == 2


async def test_cannot_sell_more_than_owned(ledger):
    ledger_service, _, _ = ledger
    service, market = open_market()
    await assert_async_error(
        "INSUFFICIENT_SHARES",
        service.sell(market_id=market.id, user_id="u1", outcome="yes", shares=1, ledger=ledger_service),
    )


async def test_yes_price_moves_with_buys(ledger):
    ledger_service, _, _ = ledger
    service, market = open_market()
    start = service.market_payload(market)["yes_price"]
    await service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=5, ledger=ledger_service)
    after_yes = service.market_payload(market)["yes_price"]
    assert after_yes > start
    await service.buy(market_id=market.id, user_id="u2", outcome="no", shares=10, ledger=ledger_service)
    after_no = service.market_payload(market)["yes_price"]
    assert after_no < after_yes


async def test_resolve_yes_settles_winners_once(ledger):
    ledger_service, wallets, transactions = ledger
    service, market = open_market()
    await service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=2, ledger=ledger_service)
    await service.buy(market_id=market.id, user_id="u2", outcome="no", shares=2, ledger=ledger_service)
    service.close_market(market.id)
    await service.resolve_market(market_id=market.id, outcome="yes", resolver_notes="YES won", ledger=ledger_service)
    count_after_first = len(transactions.docs)
    await service.resolve_market(market_id=market.id, outcome="yes", resolver_notes="YES won", ledger=ledger_service)
    winner = await wallets.find_one({"user_id": "u1"})
    loser = await wallets.find_one({"user_id": "u2"})
    assert winner["balance"] == 1100
    assert loser["balance"] < 1000
    assert len(transactions.docs) == count_after_first


async def test_resolve_no_settles_winners_once(ledger):
    ledger_service, wallets, _ = ledger
    service, market = open_market()
    await service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=2, ledger=ledger_service)
    await service.buy(market_id=market.id, user_id="u2", outcome="no", shares=2, ledger=ledger_service)
    service.close_market(market.id)
    await service.resolve_market(market_id=market.id, outcome="no", resolver_notes="NO won", ledger=ledger_service)
    winner = await wallets.find_one({"user_id": "u2"})
    loser = await wallets.find_one({"user_id": "u1"})
    assert winner["balance"] >= 1095
    assert loser["balance"] == 900


async def test_invalid_market_refunds_once(ledger):
    ledger_service, wallets, transactions = ledger
    service, market = open_market()
    await service.buy(market_id=market.id, user_id="u1", outcome="yes", shares=2, ledger=ledger_service)
    service.close_market(market.id)
    await service.resolve_market(market_id=market.id, outcome="invalid", resolver_notes="Invalid source", ledger=ledger_service)
    count_after_first = len(transactions.docs)
    await service.resolve_market(market_id=market.id, outcome="invalid", resolver_notes="Invalid source", ledger=ledger_service)
    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] == 1000
    assert len(transactions.docs) == count_after_first
