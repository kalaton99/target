import copy

import pytest
from pymongo.errors import DuplicateKeyError

from ledger.service import LedgerService
from target.wallet_bridge import (
    TargetPayoutParticipant,
    TargetWalletInsufficientFunds,
    TargetWalletRefundNotAllowed,
    lock_target_stake,
    settle_target_payout,
    unlock_target_stake,
)


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
    await service.open_wallet("winner", opening_balance=1000)
    await service.open_wallet("loser", opening_balance=1000)
    await service.open_wallet("low_balance", opening_balance=50)
    return service, wallets, transactions, idem, journals, audit


async def test_join_locks_stake(ledger):
    service, wallets, *_ = ledger

    result = await lock_target_stake(
        service,
        table_id="tbl1",
        user_id="winner",
        stake=250,
    )

    wallet = await wallets.find_one({"user_id": "winner"})
    assert result["balance"] == 750
    assert result["locked"] == 250
    assert result["locked_balance"] == 250
    assert wallet["balance"] == 750
    assert wallet["locked"] == 250
    assert wallet["locked_balance"] == 250


async def test_duplicate_join_does_not_double_lock(ledger):
    service, wallets, transactions, *_ = ledger

    first = await lock_target_stake(service, table_id="tbl1", user_id="winner", stake=250)
    second = await lock_target_stake(service, table_id="tbl1", user_id="winner", stake=250)

    wallet = await wallets.find_one({"user_id": "winner"})
    assert first == second
    assert wallet["balance"] == 750
    assert wallet["locked_balance"] == 250
    assert len(transactions.docs) == 2


async def test_pre_game_cancel_unlocks_stake(ledger):
    service, wallets, *_ = ledger
    await lock_target_stake(service, table_id="tbl1", user_id="winner", stake=250)

    result = await unlock_target_stake(
        service,
        table_id="tbl1",
        user_id="winner",
        stake=250,
        table_status="LOBBY",
    )

    wallet = await wallets.find_one({"user_id": "winner"})
    assert result["balance"] == 1000
    assert result["locked_balance"] == 0
    assert wallet["locked"] == 0
    assert wallet["locked_balance"] == 0


async def test_duplicate_cancel_does_not_double_unlock(ledger):
    service, wallets, transactions, *_ = ledger
    await lock_target_stake(service, table_id="tbl1", user_id="winner", stake=250)

    first = await unlock_target_stake(
        service,
        table_id="tbl1",
        user_id="winner",
        stake=250,
        table_status="LOBBY",
    )
    second = await unlock_target_stake(
        service,
        table_id="tbl1",
        user_id="winner",
        stake=250,
        table_status="LOBBY",
    )

    wallet = await wallets.find_one({"user_id": "winner"})
    assert first == second
    assert wallet["balance"] == 1000
    assert wallet["locked_balance"] == 0
    assert len(transactions.docs) == 4


async def test_cannot_refund_after_running_or_final_state(ledger):
    service, wallets, *_ = ledger
    await lock_target_stake(service, table_id="tbl1", user_id="winner", stake=250)

    with pytest.raises(TargetWalletRefundNotAllowed):
        await unlock_target_stake(
            service,
            table_id="tbl1",
            user_id="winner",
            stake=250,
            table_status="RUNNING",
        )
    with pytest.raises(TargetWalletRefundNotAllowed):
        await unlock_target_stake(
            service,
            table_id="tbl1",
            user_id="winner",
            stake=250,
            table_status="PAYOUT",
        )

    wallet = await wallets.find_one({"user_id": "winner"})
    assert wallet["balance"] == 750
    assert wallet["locked_balance"] == 250


async def test_payout_consumes_locked_stake(ledger):
    service, wallets, *_ = ledger
    await lock_target_stake(service, table_id="tbl1", user_id="winner", stake=250)
    await lock_target_stake(service, table_id="tbl1", user_id="loser", stake=250)

    await settle_target_payout(
        service,
        table_id="tbl1",
        round_id="hand1",
        participants=[
            TargetPayoutParticipant("winner", locked_stake=250, payout=500),
            TargetPayoutParticipant("loser", locked_stake=250, payout=0),
        ],
    )

    winner = await wallets.find_one({"user_id": "winner"})
    loser = await wallets.find_one({"user_id": "loser"})
    assert winner["locked"] == 0
    assert winner["locked_balance"] == 0
    assert loser["locked"] == 0
    assert loser["locked_balance"] == 0


async def test_winner_receives_durable_payout(ledger):
    service, wallets, *_ = ledger
    await lock_target_stake(service, table_id="tbl1", user_id="winner", stake=250)

    await settle_target_payout(
        service,
        table_id="tbl1",
        round_id="hand1",
        participants=[TargetPayoutParticipant("winner", locked_stake=250, payout=400)],
    )

    wallet = await wallets.find_one({"user_id": "winner"})
    assert wallet["balance"] == 1150
    assert wallet["locked_balance"] == 0


async def test_duplicate_settlement_does_not_double_pay(ledger):
    service, wallets, transactions, *_ = ledger
    await lock_target_stake(service, table_id="tbl1", user_id="winner", stake=250)

    participants = [TargetPayoutParticipant("winner", locked_stake=250, payout=400)]
    first = await settle_target_payout(
        service,
        table_id="tbl1",
        round_id="hand1",
        participants=participants,
    )
    transaction_count_after_first = len(transactions.docs)
    second = await settle_target_payout(
        service,
        table_id="tbl1",
        round_id="hand1",
        participants=participants,
    )

    wallet = await wallets.find_one({"user_id": "winner"})
    assert first == second
    assert wallet["balance"] == 1150
    assert wallet["locked_balance"] == 0
    assert len(transactions.docs) == transaction_count_after_first


async def test_insufficient_balance_prevents_join(ledger):
    service, wallets, *_ = ledger

    with pytest.raises(TargetWalletInsufficientFunds):
        await lock_target_stake(
            service,
            table_id="tbl1",
            user_id="low_balance",
            stake=100,
        )

    wallet = await wallets.find_one({"user_id": "low_balance"})
    assert wallet["balance"] == 50
    assert wallet["locked"] == 0
    assert wallet["locked_balance"] == 0


async def test_locked_aliases_remain_consistent(ledger):
    service, wallets, *_ = ledger

    await lock_target_stake(service, table_id="tbl1", user_id="winner", stake=125)
    wallet = await wallets.find_one({"user_id": "winner"})
    assert wallet["locked"] == wallet["locked_balance"] == 125

    await unlock_target_stake(
        service,
        table_id="tbl1",
        user_id="winner",
        stake=125,
        table_status="LOBBY",
    )
    wallet = await wallets.find_one({"user_id": "winner"})
    assert wallet["locked"] == wallet["locked_balance"] == 0
