import copy

import pytest
from pymongo.errors import DuplicateKeyError

from ledger.service import (
    InsufficientFunds,
    LedgerService,
    LockedFundsError,
    REASON_TARGET_CANCEL_UNLOCK,
    REASON_TARGET_JOIN_LOCK,
    REASON_TARGET_REFUND,
    REASON_TARGET_WIN_PAYOUT,
)


class FakeResult:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def create_index(self, *args, **kwargs):
        return None

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
    await service.open_wallet("u1", opening_balance=1000)
    return service, wallets, transactions, idem, journals, audit


async def test_balance_lock_moves_spendable_to_locked(ledger):
    service, wallets, transactions, _, _, audit = ledger

    result = await service.lock_balance(
        user_id="u1",
        amount=250,
        ref_type="TABLE",
        ref_id="tbl1",
        idempotency_key="lock-1",
    )

    wallet = await wallets.find_one({"user_id": "u1"})
    assert result["balance"] == 750
    assert result["locked_balance"] == 250
    assert wallet["balance"] == 750
    assert wallet["locked"] == 250
    assert wallet["locked_balance"] == 250
    assert sum(tx["amount"] for tx in transactions.docs) == 0
    assert {tx["source_module"] for tx in transactions.docs} == {"target"}
    assert audit.docs[-1]["action"] == "wallet_lock"


async def test_unlock_refund_releases_locked_balance(ledger):
    service, wallets, *_ = ledger
    await service.lock_balance(
        user_id="u1",
        amount=250,
        ref_type="TABLE",
        ref_id="tbl1",
        idempotency_key="lock-1",
    )

    result = await service.unlock_balance(
        user_id="u1",
        amount=100,
        reason=REASON_TARGET_REFUND,
        ref_type="TABLE",
        ref_id="tbl1",
        idempotency_key="refund-1",
    )

    wallet = await wallets.find_one({"user_id": "u1"})
    assert result["balance"] == 850
    assert result["locked_balance"] == 150
    assert wallet["balance"] == 850
    assert wallet["locked"] == 150
    assert wallet["locked_balance"] == 150


async def test_payout_settlement_is_idempotent(ledger):
    service, wallets, transactions, *_ = ledger
    await service.lock_balance(
        user_id="u1",
        amount=250,
        ref_type="TABLE",
        ref_id="tbl1",
        idempotency_key="lock-1",
    )

    first = await service.settle_locked(
        user_id="u1",
        locked_debit=250,
        payout_amount=400,
        ref_type="HAND",
        ref_id="hand1",
        idempotency_key="settle-1",
    )
    second = await service.settle_locked(
        user_id="u1",
        locked_debit=250,
        payout_amount=400,
        ref_type="HAND",
        ref_id="hand1",
        idempotency_key="settle-1",
    )

    wallet = await wallets.find_one({"user_id": "u1"})
    assert first == second
    assert wallet["balance"] == 1150
    assert wallet["locked"] == 0
    assert wallet["locked_balance"] == 0
    settle_rows = [tx for tx in transactions.docs if tx["journal_id"] == first["journal_id"]]
    assert sum(tx["amount"] for tx in settle_rows) == 0
    assert {tx["reason"] for tx in settle_rows} == {REASON_TARGET_WIN_PAYOUT}


async def test_insufficient_balance_cannot_lock(ledger):
    service, wallets, *_ = ledger

    with pytest.raises(InsufficientFunds):
        await service.lock_balance(
            user_id="u1",
            amount=1001,
            ref_type="TABLE",
            ref_id="tbl1",
            idempotency_key="lock-too-much",
        )

    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] == 1000
    assert wallet["locked"] == 0
    assert wallet["locked_balance"] == 0


async def test_insufficient_locked_balance_cannot_unlock_or_settle(ledger):
    service, wallets, *_ = ledger
    await service.lock_balance(
        user_id="u1",
        amount=100,
        ref_type="TABLE",
        ref_id="tbl1",
        idempotency_key="lock-1",
    )

    with pytest.raises(LockedFundsError):
        await service.unlock_balance(
            user_id="u1",
            amount=101,
            ref_type="TABLE",
            ref_id="tbl1",
            idempotency_key="unlock-too-much",
        )
    with pytest.raises(LockedFundsError):
        await service.settle_locked(
            user_id="u1",
            locked_debit=101,
            payout_amount=0,
            ref_type="HAND",
            ref_id="hand1",
            idempotency_key="settle-too-much",
        )

    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] == 900
    assert wallet["locked"] == 100
    assert wallet["locked_balance"] == 100


async def test_reason_enums_are_available_and_stored(ledger):
    service, _, transactions, *_ = ledger

    await service.lock_balance(
        user_id="u1",
        amount=10,
        reason=REASON_TARGET_JOIN_LOCK,
        ref_type="TABLE",
        ref_id="tbl1",
        idempotency_key="lock-1",
    )
    await service.unlock_balance(
        user_id="u1",
        amount=10,
        reason=REASON_TARGET_CANCEL_UNLOCK,
        ref_type="TABLE",
        ref_id="tbl1",
        idempotency_key="unlock-1",
    )

    assert {tx["reason"] for tx in transactions.docs} == {
        REASON_TARGET_JOIN_LOCK,
        REASON_TARGET_CANCEL_UNLOCK,
    }
