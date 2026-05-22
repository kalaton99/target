"""Backend tests for /api/v2/dev/spawn_solo_table (target_score support)
and /api/v2/dev/teardown_solo_table (Deal-Again cleanup).

Covers the bug-fix scope from the 2026-01 Deal-Again spec:
  - back-compat: no body  → target=31, 4 seats, 1 bot
  - target=41           → 4 seats, 1 bot
  - target=51           → 5 seats, 2 bots
  - target=61          → 5 seats, 2 bots
  - invalid target      → 400 INVALID_TARGET_SCORE
  - non-int target      → 400 INVALID_TARGET_SCORE
  - teardown(valid)     → ok+existed=true, then idempotent existed=false
  - teardown(no body)   → 400 MISSING_TABLE_ID
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
SPAWN = f"{BASE_URL}/api/v2/dev/spawn_solo_table"
TEARDOWN = f"{BASE_URL}/api/v2/dev/teardown_solo_table"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _spawn(session, body=None):
    if body is None:
        return session.post(SPAWN, timeout=15)
    return session.post(SPAWN, json=body, timeout=15)


# --- spawn target_score handling ---

def test_spawn_no_body_defaults_target_31(session):
    r = _spawn(session)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["target_score"] == 31
    assert d["seats"] == 4
    assert isinstance(d.get("bot_user_ids"), list)
    assert len(d["bot_user_ids"]) == 1
    # cleanup
    session.post(TEARDOWN, json={"table_id": d["table_id"]}, timeout=10)


def test_spawn_target_41(session):
    r = _spawn(session, {"target_score": 41})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["target_score"] == 41
    assert d["seats"] == 4
    assert len(d["bot_user_ids"]) == 1
    session.post(TEARDOWN, json={"table_id": d["table_id"]}, timeout=10)


def test_spawn_target_51_two_bots(session):
    r = _spawn(session, {"target_score": 51})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["target_score"] == 51
    assert d["seats"] == 5
    assert len(d["bot_user_ids"]) == 2
    session.post(TEARDOWN, json={"table_id": d["table_id"]}, timeout=10)


def test_spawn_target_61_two_bots(session):
    r = _spawn(session, {"target_score": 61})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["target_score"] == 61
    assert d["seats"] == 5
    assert len(d["bot_user_ids"]) == 2
    session.post(TEARDOWN, json={"table_id": d["table_id"]}, timeout=10)


def test_spawn_invalid_target_score_999(session):
    r = _spawn(session, {"target_score": 999})
    assert r.status_code == 400, r.text
    body = r.json()
    # FastAPI wraps detail in {detail: {code,...}}
    detail = body.get("detail", body)
    assert detail.get("code") == "INVALID_TARGET_SCORE"


def test_spawn_non_integer_target_score(session):
    r = _spawn(session, {"target_score": "abc"})
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", {})
    assert detail.get("code") == "INVALID_TARGET_SCORE"


# --- teardown ---

def test_teardown_idempotent(session):
    # First spawn a table to have a real table_id.
    r = _spawn(session, {"target_score": 31})
    assert r.status_code == 200
    table_id = r.json()["table_id"]

    r1 = session.post(TEARDOWN, json={"table_id": table_id}, timeout=10)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["ok"] is True
    assert d1["existed"] is True

    # Second call should be idempotent.
    r2 = session.post(TEARDOWN, json={"table_id": table_id}, timeout=10)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2["ok"] is True
    assert d2["existed"] is False


def test_teardown_missing_table_id(session):
    r = session.post(TEARDOWN, json={}, timeout=10)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", {})
    assert detail.get("code") == "MISSING_TABLE_ID"
