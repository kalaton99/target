import copy
from pathlib import Path

import pytest
from pymongo.errors import DuplicateKeyError

from flipget.models import FLIPGET_SEATS
from flipget.service import FlipgetError, FlipgetService
from flipget.wallet_bridge import (
    FlipgetRefundNotAllowed,
    lock_flipget_stake,
    unlock_flipget_stake,
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
    for user_id in ("u1", "u2", "u3"):
        await service.open_wallet(user_id, opening_balance=1000)
    return service, wallets, transactions


def make_service(result="heads"):
    return FlipgetService(coin_rng=lambda: result)


def make_service_sequence(results):
    values = list(results)

    def rng():
        return values.pop(0)

    return FlipgetService(coin_rng=rng)


def two_player_ready(service, result_side="heads", mode="single_flip"):
    table = service.create_table(creator_user_id="u1", username="u1", mode=mode)
    service.join_table(table_id=table.id, user_id="u2", username="u2")
    service.choose_side(table_id=table.id, user_id="u1", side="heads")
    service.choose_side(table_id=table.id, user_id="u2", side="tails")
    service.ready(table_id=table.id, user_id="u1")
    service.ready(table_id=table.id, user_id="u2")
    return table


def test_create_table_has_exactly_two_seats_and_rejects_other_sizes():
    service = make_service()
    table = service.create_table(creator_user_id="u1", max_players=2)
    assert table.max_players == FLIPGET_SEATS == 2
    assert table.mode == "single_flip"
    assert table.to_dict()["mode_label"] == "Single Flip"
    with pytest.raises(FlipgetError) as err:
        service.create_table(creator_user_id="u2", max_players=3)
    assert err.value.code == "INVALID_TABLE_SIZE"
    with pytest.raises(FlipgetError) as err:
        service.create_table(creator_user_id="u3", mode="double_or_nothing")
    assert err.value.code == "INVALID_MODE"


def test_flipget_runtime_ui_exposes_modes_and_exit_guard_copy():
    source = (Path(__file__).resolve().parents[2] / "frontend/src/pages/FlipgetPage.jsx").read_text(encoding="utf-8")

    assert "Single Flip" in source
    assert "Best of 3" in source
    assert "Best of 5" in source
    assert "Mode:" in source
    assert "Heads {table.score?.heads || 0} - Tails {table.score?.tails || 0}" in source
    assert "Leave Active Flipget?" in source
    assert "Leaving may cause the current stake or participation to be lost." in source


async def test_create_locks_creator_stake_once(ledger):
    service, wallets, transactions = ledger
    await lock_flipget_stake(service, table_id="fg1", user_id="u1", stake=100)
    await lock_flipget_stake(service, table_id="fg1", user_id="u1", stake=100)
    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] == 900
    assert wallet["locked"] == wallet["locked_balance"] == 100
    assert len(transactions.docs) == 2


async def test_join_locks_joiner_stake_once(ledger):
    service, wallets, transactions = ledger
    await lock_flipget_stake(service, table_id="fg1", user_id="u2", stake=100)
    await lock_flipget_stake(service, table_id="fg1", user_id="u2", stake=100)
    wallet = await wallets.find_one({"user_id": "u2"})
    assert wallet["balance"] == 900
    assert wallet["locked_balance"] == 100
    assert len(transactions.docs) == 2


def test_reject_third_player_and_duplicate_user():
    service = make_service()
    table = service.create_table(creator_user_id="u1")
    service.join_table(table_id=table.id, user_id="u2")
    with pytest.raises(FlipgetError) as err:
        service.join_table(table_id=table.id, user_id="u1")
    assert err.value.code == "DUPLICATE_USER"
    with pytest.raises(FlipgetError) as err:
        service.join_table(table_id=table.id, user_id="u3")
    assert err.value.code == "TABLE_FULL"


def test_choose_heads_and_tails():
    service = make_service()
    table = service.create_table(creator_user_id="u1")
    service.join_table(table_id=table.id, user_id="u2")
    service.choose_side(table_id=table.id, user_id="u1", side="heads")
    service.choose_side(table_id=table.id, user_id="u2", side="tails")
    assert table.seats[0].side == "heads"
    assert table.seats[1].side == "tails"


def test_reject_duplicate_side_and_invalid_side():
    service = make_service()
    table = service.create_table(creator_user_id="u1")
    service.join_table(table_id=table.id, user_id="u2")
    service.choose_side(table_id=table.id, user_id="u1", side="heads")
    with pytest.raises(FlipgetError) as err:
        service.choose_side(table_id=table.id, user_id="u2", side="heads")
    assert err.value.code == "SIDE_ALREADY_TAKEN"
    with pytest.raises(FlipgetError) as err:
        service.choose_side(table_id=table.id, user_id="u2", side="edge")
    assert err.value.code == "INVALID_SIDE"


def test_reject_ready_without_side():
    table = make_service().create_table(creator_user_id="u1")
    with pytest.raises(FlipgetError) as err:
        make_service().ready(table_id=table.id, user_id="u1")
    assert err.value.code == "TABLE_NOT_FOUND"
    service = make_service()
    table = service.create_table(creator_user_id="u1")
    with pytest.raises(FlipgetError) as err:
        service.ready(table_id=table.id, user_id="u1")
    assert err.value.code == "SIDE_REQUIRED"


async def test_reject_flip_before_two_players_or_before_both_ready():
    service = make_service()
    table = service.create_table(creator_user_id="u1")
    with pytest.raises(FlipgetError) as err:
        await service.flip(table_id=table.id, user_id="u1")
    assert err.value.code == "REQUIRES_EXACTLY_2_SEATS"
    service.join_table(table_id=table.id, user_id="u2")
    service.choose_side(table_id=table.id, user_id="u1", side="heads")
    service.choose_side(table_id=table.id, user_id="u2", side="tails")
    service.ready(table_id=table.id, user_id="u1")
    with pytest.raises(FlipgetError) as err:
        await service.flip(table_id=table.id, user_id="u1")
    assert err.value.code == "PLAYERS_NOT_READY"


async def test_valid_flip_produces_backend_result_and_heads_wins_when_heads():
    service = make_service("heads")
    table = two_player_ready(service)
    flipped = await service.flip(table_id=table.id, user_id="u1")
    assert flipped.round.result == "heads"
    assert flipped.round.winner_user_id == "u1"
    assert flipped.round.loser_user_id == "u2"
    assert flipped.status == "settled"
    assert flipped.score == {"heads": 1, "tails": 0}
    assert flipped.winning_side == "heads"


async def test_tails_player_wins_when_result_tails():
    service = make_service("tails")
    table = two_player_ready(service)
    flipped = await service.flip(table_id=table.id, user_id="u2")
    assert flipped.round.result == "tails"
    assert flipped.round.winner_user_id == "u2"
    assert flipped.round.loser_user_id == "u1"


async def test_best_of_3_resolves_when_one_side_reaches_two_wins():
    service = make_service_sequence(["heads", "heads"])
    table = two_player_ready(service, mode="best_of_3")

    first = await service.flip(table_id=table.id, user_id="u1")
    assert first.status == "ready"
    assert first.score == {"heads": 1, "tails": 0}
    assert first.to_dict()["current_round_number"] == 2

    second = await service.flip(table_id=table.id, user_id="u1")
    assert second.status == "settled"
    assert second.score == {"heads": 2, "tails": 0}
    assert second.winning_side == "heads"
    assert second.to_dict()["wins_required"] == 2


async def test_best_of_5_resolves_when_one_side_reaches_three_wins():
    service = make_service_sequence(["heads", "tails", "heads", "heads"])
    table = two_player_ready(service, mode="best_of_5")

    for _ in range(3):
        progressed = await service.flip(table_id=table.id, user_id="u1")
        assert progressed.status == "ready"

    final = await service.flip(table_id=table.id, user_id="u1")
    assert final.status == "settled"
    assert final.score == {"heads": 3, "tails": 1}
    assert final.winning_side == "heads"
    assert final.to_dict()["max_rounds"] == 5


async def test_cannot_flip_after_resolved_table():
    service = make_service("heads")
    table = two_player_ready(service)
    await service.flip(table_id=table.id, user_id="u1")
    with pytest.raises(FlipgetError) as err:
        await service.flip(table_id=table.id, user_id="u1")
    assert err.value.code == "TABLE_ALREADY_SETTLED"


async def test_pre_flip_leave_unlocks_once(ledger):
    service, wallets, transactions = ledger
    await lock_flipget_stake(service, table_id="fg_leave", user_id="u1", stake=100)
    await unlock_flipget_stake(service, table_id="fg_leave", user_id="u1", stake=100, table_status="waiting")
    await unlock_flipget_stake(service, table_id="fg_leave", user_id="u1", stake=100, table_status="waiting")
    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] == 1000
    assert wallet["locked"] == wallet["locked_balance"] == 0
    assert len(transactions.docs) == 4


async def test_flipping_and_settled_leave_does_not_unlock(ledger):
    service, wallets, transactions = ledger
    await lock_flipget_stake(service, table_id="fg_started", user_id="u1", stake=100)
    before = len(transactions.docs)
    for status in ("flipping", "settled"):
        with pytest.raises(FlipgetRefundNotAllowed):
            await unlock_flipget_stake(
                service,
                table_id="fg_started",
                user_id="u1",
                stake=100,
                table_status=status,
            )
    wallet = await wallets.find_one({"user_id": "u1"})
    assert wallet["balance"] == 900
    assert wallet["locked_balance"] == 100
    assert len(transactions.docs) == before


async def test_settlement_pays_winner_once_and_repeated_settlement_does_not_double_pay(ledger):
    ledger_service, wallets, transactions = ledger
    game = make_service("heads")
    table = two_player_ready(game)
    await lock_flipget_stake(ledger_service, table_id=table.id, user_id="u1", stake=100)
    await lock_flipget_stake(ledger_service, table_id=table.id, user_id="u2", stake=100)
    await game.flip(table_id=table.id, user_id="u1", ledger=ledger_service)
    count_after_first = len(transactions.docs)
    await game.settle(table.id, ledger_service)
    winner = await wallets.find_one({"user_id": "u1"})
    loser = await wallets.find_one({"user_id": "u2"})
    assert winner["balance"] == 1100
    assert winner["locked_balance"] == 0
    assert loser["balance"] == 900
    assert loser["locked_balance"] == 0
    assert len(transactions.docs) == count_after_first


async def test_deal_again_reset_does_not_duplicate_settlement(ledger):
    ledger_service, _, transactions = ledger
    game = make_service("heads")
    table = two_player_ready(game)
    await lock_flipget_stake(ledger_service, table_id=table.id, user_id="u1", stake=100)
    await lock_flipget_stake(ledger_service, table_id=table.id, user_id="u2", stake=100)
    await game.flip(table_id=table.id, user_id="u1", ledger=ledger_service)
    count_after_settle = len(transactions.docs)
    next_table = game.deal_again(table_id=table.id, user_id="u1")
    assert next_table.id != table.id
    assert next_table.status == "waiting"
    assert len(transactions.docs) == count_after_settle
