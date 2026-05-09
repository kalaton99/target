import copy

import pytest
from pymongo.errors import DuplicateKeyError

from diceget.models import DICEGET_SEATS, SUPPORTED_TARGETS
from diceget.service import DicegetError, DicegetService
from diceget.wallet_bridge import (
    DicegetRefundNotAllowed,
    lock_diceget_stake,
    unlock_diceget_stake,
)
from ledger.service import LedgerService


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
    for user_id in ("u1", "u2", "u3", "u4"):
        await service.open_wallet(user_id, opening_balance=1000)
    return service, wallets, transactions


def make_service(rolls=None):
    values = list(rolls or [3, 4, 2, 5, 6, 6, 1, 1])

    def rng():
        return values.pop(0)

    return DicegetService(dice_rng=rng)


def fill_four(service, target=30):
    table = service.create_table(creator_user_id="u1", username="u1", target_score=target)
    for user_id in ("u2", "u3", "u4"):
        service.join_table(table_id=table.id, user_id=user_id, username=user_id)
    return table


def test_supported_targets_are_30_50_75_100():
    assert SUPPORTED_TARGETS == {30, 50, 75, 100}
    service = make_service()
    for target in (30, 50, 75, 100):
        assert service.create_table(creator_user_id=f"u{target}", target_score=target).target_score == target


def test_reject_target_250():
    with pytest.raises(DicegetError, match="INVALID_TARGET_SCORE"):
        make_service().create_table(creator_user_id="u1", target_score=250)


def test_every_table_has_exactly_four_seats_and_rejects_other_sizes():
    service = make_service()
    table = service.create_table(creator_user_id="u1", target_score=30)
    assert table.max_players == DICEGET_SEATS == 4
    with pytest.raises(DicegetError) as err:
        service.create_table(creator_user_id="u2", target_score=30, max_players=5)
    assert err.value.code == "INVALID_TABLE_SIZE"
    with pytest.raises(DicegetError) as err:
        service.create_table(creator_user_id="u3", target_score=30, max_players=8)
    assert err.value.code == "INVALID_TABLE_SIZE"


async def test_create_table_locks_creator_stake_once(ledger):
    service, wallets, transactions = ledger
    await lock_diceget_stake(service, table_id="dg1", user_id="u1", stake=100)
    await lock_diceget_stake(service, table_id="dg1", user_id="u1", stake=100)
    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] == 900
    assert wallet["locked"] == wallet["locked_balance"] == 100
    assert len(transactions.docs) == 2


async def test_join_locks_joiner_stake_once_and_duplicate_join_does_not_double_lock(ledger):
    ledger_service, wallets, transactions = ledger
    game = make_service()
    table = game.create_table(creator_user_id="u1", target_score=30)
    game.join_table(table_id=table.id, user_id="u2")
    game.join_table(table_id=table.id, user_id="u2")
    await lock_diceget_stake(ledger_service, table_id=table.id, user_id="u2", stake=100)
    await lock_diceget_stake(ledger_service, table_id=table.id, user_id="u2", stake=100)
    wallet = await wallets.find_one({"user_id": "u2"})
    assert len(table.seats) == 2
    assert wallet["balance"] == 900
    assert wallet["locked_balance"] == 100
    assert len(transactions.docs) == 2


def test_max_three_bots_and_start_requires_four_occupied_seats():
    service = make_service()
    table = service.create_table(creator_user_id="u1", target_score=30)
    with pytest.raises(DicegetError, match="REQUIRES_EXACTLY_4_SEATS"):
        service.start_table(table_id=table.id, user_id="u1")
    service.add_bot(table_id=table.id, profile="safe")
    service.add_bot(table_id=table.id, profile="normal")
    service.add_bot(table_id=table.id, profile="aggressive")
    with pytest.raises(DicegetError, match="MAX_BOTS_EXCEEDED|TABLE_FULL"):
        service.add_bot(table_id=table.id, profile="normal")
    started = service.start_table(table_id=table.id, user_id="u1")
    assert started.status == "active"
    assert len(started.seats) == 4


def test_roll_generates_two_dice_and_increases_score():
    service = make_service([2, 5])
    table = fill_four(service)
    service.start_table(table_id=table.id, user_id="u1")
    service.roll(table_id=table.id, user_id="u1")
    roll = table.rolls[-1]
    assert 1 <= roll.dice_1 <= 6
    assert 1 <= roll.dice_2 <= 6
    assert roll.total == 7
    assert table.seats[0].score == 7


def test_bust_when_score_exceeds_target():
    service = make_service([6, 6, 6, 6, 6, 6])
    table = fill_four(service, target=30)
    service.start_table(table_id=table.id, user_id="u1")
    service.roll(table_id=table.id, user_id="u1")
    service.roll(table_id=table.id, user_id="u1")
    service.roll(table_id=table.id, user_id="u1")
    assert table.seats[0].status == "busted"
    assert table.current_turn_user_id == "u2"


def test_hold_locks_score_and_forfeit_excludes_player():
    service = make_service([4, 5])
    table = fill_four(service)
    service.start_table(table_id=table.id, user_id="u1")
    service.roll(table_id=table.id, user_id="u1")
    service.hold(table_id=table.id, user_id="u1")
    assert table.seats[0].status == "held"
    assert table.seats[0].locked_score == 9
    service.forfeit(table_id=table.id, user_id="u2")
    assert table.seats[1].status == "forfeited"


def test_turn_advancement_skips_inactive_players():
    service = make_service([1, 1])
    table = fill_four(service)
    service.start_table(table_id=table.id, user_id="u1")
    service.hold(table_id=table.id, user_id="u1")
    service.forfeit(table_id=table.id, user_id="u2")
    assert table.current_turn_user_id == "u3"


def test_showdown_picks_best_valid_score_and_tied_winners_are_stored():
    service = make_service()
    table = fill_four(service)
    table.status = "showdown"
    table.seats[0].status = "held"
    table.seats[0].locked_score = 20
    table.seats[1].status = "held"
    table.seats[1].locked_score = 20
    table.seats[2].status = "held"
    table.seats[2].locked_score = 19
    table.seats[3].status = "busted"
    table.winners = service._compute_winners(table)
    assert table.winners == ["u1", "u2"]


async def test_pre_game_leave_unlocks_once(ledger):
    service, wallets, transactions = ledger
    await lock_diceget_stake(service, table_id="dg_leave", user_id="u1", stake=100)
    await unlock_diceget_stake(service, table_id="dg_leave", user_id="u1", stake=100, table_status="waiting")
    await unlock_diceget_stake(service, table_id="dg_leave", user_id="u1", stake=100, table_status="waiting")
    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] == 1000
    assert wallet["locked"] == wallet["locked_balance"] == 0
    assert len(transactions.docs) == 4


async def test_active_showdown_settled_leave_does_not_unlock(ledger):
    service, wallets, transactions = ledger
    await lock_diceget_stake(service, table_id="dg_started", user_id="u1", stake=100)
    before = len(transactions.docs)
    for status in ("active", "showdown", "settled"):
        with pytest.raises(DicegetRefundNotAllowed):
            await unlock_diceget_stake(
                service,
                table_id="dg_started",
                user_id="u1",
                stake=100,
                table_status=status,
            )
    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] == 900
    assert wallet["locked_balance"] == 100
    assert len(transactions.docs) == before


async def test_settlement_pays_winners_once_and_repeated_settlement_does_not_double_pay(ledger):
    ledger_service, wallets, transactions = ledger
    game = make_service()
    table = fill_four(game)
    for user_id in ("u1", "u2", "u3", "u4"):
        await lock_diceget_stake(ledger_service, table_id=table.id, user_id=user_id, stake=100)
    table.status = "showdown"
    for seat, score in zip(table.seats, [25, 20, 18, 10]):
        seat.status = "held"
        seat.locked_score = score
    first = await game.settle(table.id, ledger_service)
    count_after_first = len(transactions.docs)
    second = await game.settle(table.id, ledger_service)
    winner = await wallets.find_one({"user_id": "u1"})
    loser = await wallets.find_one({"user_id": "u2"})
    assert first is second
    assert winner["balance"] == 1300
    assert winner["locked_balance"] == 0
    assert loser["balance"] == 900
    assert loser["locked_balance"] == 0
    assert len(transactions.docs) == count_after_first


async def test_deal_again_reset_does_not_duplicate_settlement(ledger):
    ledger_service, _, transactions = ledger
    game = make_service()
    table = fill_four(game)
    for user_id in ("u1", "u2", "u3", "u4"):
        await lock_diceget_stake(ledger_service, table_id=table.id, user_id=user_id, stake=100)
    table.status = "showdown"
    for seat, score in zip(table.seats, [25, 20, 18, 10]):
        seat.status = "held"
        seat.locked_score = score
    await game.settle(table.id, ledger_service)
    count_after_settle = len(transactions.docs)
    next_table = game.deal_again(table_id=table.id, user_id="u1")
    assert next_table.id != table.id
    assert next_table.status == "waiting"
    assert len(transactions.docs) == count_after_settle
