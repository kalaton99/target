import copy

import pytest

from diceget.models import SUPPORTED_SCORE_GOALS
from diceget.service import DicegetService
from flipget.models import FLIPGET_MODES
from flipget.service import FlipgetService
from jackget.models import JACKGET_MAX_PLAYERS, JACKGET_MIN_PLAYERS
from jackget.service import JackgetService
from lobby import service as target_lobby_service


class FakeResult:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction):
        reverse = direction < 0
        self.docs.sort(key=lambda doc: doc.get(key, 0), reverse=reverse)
        return self

    def __aiter__(self):
        self._iter = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return copy.deepcopy(next(self._iter))
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def insert_one(self, doc):
        self.docs.append(copy.deepcopy(doc))
        return FakeResult()

    def find(self, filt, projection=None):
        return FakeCursor([
            copy.deepcopy(doc)
            for doc in self.docs
            if _matches(doc, filt)
        ])

    async def find_one(self, filt, projection=None):
        for doc in self.docs:
            if _matches(doc, filt):
                return copy.deepcopy(doc)
        return None

    async def find_one_and_update(self, filt, update, return_document=None, projection=None):
        for index, doc in enumerate(self.docs):
            if not _matches(doc, filt):
                continue
            for key, value in update.get("$set", {}).items():
                doc[key] = value
            for key, value in update.get("$push", {}).items():
                doc.setdefault(key, []).append(copy.deepcopy(value))
            self.docs[index] = doc
            return copy.deepcopy(doc)
        return None


class FakeTargetDb:
    def __init__(self):
        self.lobby_tables = FakeCollection()
        self.lobby_users = FakeCollection([
            {"user_id": "u_real", "username": "real_user", "created_at": 1},
        ])

    def __getitem__(self, key):
        return getattr(self, key)


def _matches(doc, filt):
    for key, expected in filt.items():
        if "." in key and isinstance(expected, dict) and "$exists" in expected:
            root, index = key.split(".", 1)
            values = doc.get(root, [])
            exists = int(index) < len(values)
            if exists != bool(expected["$exists"]):
                return False
            continue
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            continue
        if actual != expected:
            return False
    return True


@pytest.mark.parametrize("service_cls,expected_values", [
    (DicegetService, SUPPORTED_SCORE_GOALS),
    (FlipgetService, set(FLIPGET_MODES)),
])
def test_in_memory_game_bootstrap_is_idempotent(monkeypatch, service_cls, expected_values):
    monkeypatch.setenv("WINSGET_LOCAL_TABLE_BOOTSTRAP", "1")
    service = service_cls()

    first = service.list_tables()
    second = service.list_tables()

    assert len(first) == 5
    assert [table["table_id"] for table in first] == [table["table_id"] for table in second]
    assert all(table["status"] == "waiting" for table in first)
    if service_cls is DicegetService:
        assert {table["score_goal"] for table in first}.issubset(expected_values)
    else:
        assert {table["mode"] for table in first}.issubset(expected_values)


def test_diceget_bootstrap_table_transfers_creator_to_first_joiner(monkeypatch):
    monkeypatch.setenv("WINSGET_LOCAL_TABLE_BOOTSTRAP", "1")
    service = DicegetService()
    seeded = service.list_tables()[0]

    joined = service.join_table(table_id=seeded["table_id"], user_id="u_real", username="Player")

    assert joined.creator_user_id == "u_real"
    assert len(joined.seats) == 1
    assert joined.seats[0].username == "Player"


def test_flipget_bootstrap_table_transfers_creator_to_first_joiner(monkeypatch):
    monkeypatch.setenv("WINSGET_LOCAL_TABLE_BOOTSTRAP", "1")
    service = FlipgetService()
    seeded = service.list_tables()[0]

    joined = service.join_table(table_id=seeded["table_id"], user_id="u_real", username="Player")

    assert joined.creator_user_id == "u_real"
    assert len(joined.seats) == 1
    assert joined.seats[0].username == "Player"


def test_jackget_bootstrap_is_idempotent_and_uses_valid_table_sizes(monkeypatch):
    monkeypatch.setenv("WINSGET_LOCAL_TABLE_BOOTSTRAP", "1")
    service = JackgetService()

    first = service.list_tables()
    second = service.list_tables()

    assert len(first) == 5
    assert [table["table_id"] for table in first] == [table["table_id"] for table in second]
    assert {table["max_players"] for table in first}.issubset(set(range(JACKGET_MIN_PLAYERS, JACKGET_MAX_PLAYERS + 1)))


def test_jackget_bootstrap_table_transfers_creator_to_first_joiner(monkeypatch):
    monkeypatch.setenv("WINSGET_LOCAL_TABLE_BOOTSTRAP", "1")
    service = JackgetService()
    seeded = service.list_tables()[0]

    joined = service.join_table(table_id=seeded["table_id"], user_id="u_real", username="Player")

    assert joined.creator_user_id == "u_real"
    assert len(joined.seats) == 1
    assert joined.seats[0].username == "Player"


async def test_target_bootstrap_creates_valid_real_lobby_tables_and_transfers_creator(monkeypatch):
    monkeypatch.setenv("WINSGET_LOCAL_TABLE_BOOTSTRAP", "1")
    db = FakeTargetDb()

    first = await target_lobby_service.list_tables(db)
    second = await target_lobby_service.list_tables(db)

    assert len(first) == 5
    assert [table["table_id"] for table in first] == [table["table_id"] for table in second]
    assert {table["target_score"] for table in first}.issubset({31, 41, 51, 61})
    assert all(table["status"] == "LOBBY" for table in first)
    assert all(len(table["seats"]) == 0 for table in first)

    joined = await target_lobby_service.join_table(db, table_id=first[0]["table_id"], user_id="u_real")

    assert joined["creator_user_id"] == "u_real"
    assert len(joined["seats"]) == 1
    assert joined["seats"][0]["username"] == "real_user"
