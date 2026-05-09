import copy
from pathlib import Path

import pytest
from pymongo.errors import DuplicateKeyError

from game_engine.types import GameState, PlayerState
from ledger.service import LedgerService
from realtime_v2.bridge import EngineBridge
from realtime_v2.pubsub import PubSub
from target.wallet_bridge import (
    TargetWalletRefundNotAllowed,
    lock_target_stake,
    settle_target_state_if_payout,
    unlock_target_stake,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


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
    for user_id in ("creator", "joiner", "winner", "loser"):
        await service.open_wallet(user_id, opening_balance=1000)
    return service, wallets, transactions


async def test_create_table_boundary_locks_creator_stake_exactly_once(ledger):
    service, wallets, transactions = ledger

    first = await lock_target_stake(
        service,
        table_id="tbl_create",
        user_id="creator",
        stake=100,
    )
    second = await lock_target_stake(
        service,
        table_id="tbl_create",
        user_id="creator",
        stake=100,
    )

    wallet = await wallets.find_one({"user_id": "creator"})
    assert first == second
    assert wallet["balance"] == 900
    assert wallet["locked"] == wallet["locked_balance"] == 100
    assert len(transactions.docs) == 2


async def test_join_table_boundary_locks_joiner_stake_exactly_once(ledger):
    service, wallets, transactions = ledger

    first = await lock_target_stake(
        service,
        table_id="tbl_join",
        user_id="joiner",
        stake=100,
    )
    second = await lock_target_stake(
        service,
        table_id="tbl_join",
        user_id="joiner",
        stake=100,
    )

    wallet = await wallets.find_one({"user_id": "joiner"})
    assert first == second
    assert wallet["balance"] == 900
    assert wallet["locked"] == wallet["locked_balance"] == 100
    assert len(transactions.docs) == 2


async def test_pre_game_leave_unlocks_exactly_once(ledger):
    service, wallets, transactions = ledger
    await lock_target_stake(service, table_id="tbl_leave", user_id="creator", stake=100)

    first = await unlock_target_stake(
        service,
        table_id="tbl_leave",
        user_id="creator",
        stake=100,
        table_status="LOBBY",
    )
    second = await unlock_target_stake(
        service,
        table_id="tbl_leave",
        user_id="creator",
        stake=100,
        table_status="LOBBY",
    )

    wallet = await wallets.find_one({"user_id": "creator"})
    assert first == second
    assert wallet["balance"] == 1000
    assert wallet["locked"] == wallet["locked_balance"] == 0
    assert len(transactions.docs) == 4


async def test_leave_after_running_or_payout_does_not_unlock(ledger):
    service, wallets, transactions = ledger
    await lock_target_stake(service, table_id="tbl_started", user_id="creator", stake=100)
    before_count = len(transactions.docs)

    with pytest.raises(TargetWalletRefundNotAllowed):
        await unlock_target_stake(
            service,
            table_id="tbl_started",
            user_id="creator",
            stake=100,
            table_status="RUNNING",
        )
    with pytest.raises(TargetWalletRefundNotAllowed):
        await unlock_target_stake(
            service,
            table_id="tbl_started",
            user_id="creator",
            stake=100,
            table_status="PAYOUT",
        )

    wallet = await wallets.find_one({"user_id": "creator"})
    assert wallet["balance"] == 900
    assert wallet["locked"] == wallet["locked_balance"] == 100
    assert len(transactions.docs) == before_count


async def test_waiting_room_state_does_not_publish_settlement_prematurely(ledger):
    service, wallets, transactions = ledger
    await lock_target_stake(service, table_id="tbl_waiting", user_id="winner", stake=100)
    state = GameState(table_id="tbl_waiting", hand_id="hand_waiting", phase="WAITING", stake=100)
    state.players = [
        PlayerState(seat_index=0, user_id="winner", username="Winner", balance_at_start=1000),
    ]
    before_count = len(transactions.docs)

    result = await settle_target_state_if_payout(service, state=state)

    wallet = await wallets.find_one({"user_id": "winner"})
    assert result == []
    assert wallet["balance"] == 900
    assert wallet["locked"] == wallet["locked_balance"] == 100
    assert len(transactions.docs) == before_count


async def test_repeated_payout_publication_does_not_double_pay(ledger):
    service, wallets, transactions = ledger
    await lock_target_stake(service, table_id="tbl_pay", user_id="winner", stake=100)
    await lock_target_stake(service, table_id="tbl_pay", user_id="loser", stake=100)
    state = GameState(table_id="tbl_pay", hand_id="hand1", phase="PAYOUT", stake=100)
    state.players = [
        PlayerState(
            seat_index=0,
            user_id="winner",
            username="Winner",
            balance_at_start=1000,
            payout=200,
        ),
        PlayerState(
            seat_index=1,
            user_id="loser",
            username="Loser",
            balance_at_start=1000,
            payout=0,
        ),
    ]
    bridge = EngineBridge(PubSub(), target_wallet_ledger=service)

    await bridge._publish_state("tbl_pay", state, [])
    count_after_first_publish = len(transactions.docs)
    await bridge._publish_state("tbl_pay", state, [])

    winner = await wallets.find_one({"user_id": "winner"})
    loser = await wallets.find_one({"user_id": "loser"})
    assert winner["balance"] == 1100
    assert winner["locked"] == winner["locked_balance"] == 0
    assert loser["balance"] == 900
    assert loser["locked"] == loser["locked_balance"] == 0
    assert len(transactions.docs) == count_after_first_publish


def test_deal_again_uses_dev_spawn_flow_without_wallet_bridge_locking():
    play_page = (REPO_ROOT / "frontend" / "src" / "pages" / "PlayPage.jsx").read_text(
        encoding="utf-8",
    )
    dev_router = (REPO_ROOT / "backend" / "realtime_v2" / "dev_router.py").read_text(
        encoding="utf-8",
    )

    assert "/api/v2/dev/teardown_solo_table" in play_page
    assert "/api/v2/dev/spawn_solo_table" in play_page
    assert "lock_target_stake" not in dev_router
    assert "target.wallet_bridge" not in dev_router


def test_platform_shell_and_target_routes_are_still_present():
    app_js = (REPO_ROOT / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    platform_pages = (
        REPO_ROOT / "frontend" / "src" / "pages" / "PlatformPages.jsx"
    ).read_text(encoding="utf-8")

    assert 'path="/"' in app_js
    assert 'path="/games"' in app_js
    assert 'path="/games/target"' in app_js
    assert 'to="/lobby"' in app_js
    assert "PlatformHome" in platform_pages
    assert "GamesPage" in platform_pages
    assert "Existing strategic table game" in platform_pages
