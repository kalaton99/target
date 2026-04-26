"""Phase 11 P2 — Lobby HTTP + integration tests (live backend).

These tests hit the running supervisor-managed backend (REACT_APP_BACKEND_URL)
to avoid the motor/asyncio event-loop binding issues that occur when using
FastAPI TestClient with module-scope mongo clients.

Covers:
  - guest auth idempotency (same username -> same user_id)
  - invalid username rejected
  - create / list / join / leave / start
  - join idempotency
  - max_players enforcement
  - non-creator can't START
  - START transitions to RUNNING
  - end-to-end: 2 real users connect via WS to the same table
  - solo creator START spawns a bot fallback
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests
from websockets.sync.client import connect as ws_connect

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://target-poker.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")

TIMEOUT = 10


def _auth(username):
    r = requests.post(f"{API}/v2/lobby/auth", json={"username": username}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _name(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


# ============================================================
# Auth
# ============================================================

class TestAuth:
    def test_register_returns_token_and_user_id(self):
        u = _auth(_name("alice"))
        assert u["user_id"].startswith("u_")
        assert isinstance(u["token"], str) and len(u["token"]) > 30

    def test_same_username_returns_same_user_id(self):
        name = _name("bob")
        a = _auth(name)
        b = _auth(name)
        assert a["user_id"] == b["user_id"]

    def test_invalid_username_rejected(self):
        r = requests.post(f"{API}/v2/lobby/auth", json={"username": "@@"}, timeout=TIMEOUT)
        assert r.status_code in (400, 422)

    def test_me_requires_auth(self):
        r = requests.get(f"{API}/v2/lobby/me", timeout=TIMEOUT)
        assert r.status_code == 401

    def test_me_returns_user(self):
        u = _auth(_name("carol"))
        r = requests.get(f"{API}/v2/lobby/me", headers=_h(u["token"]), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json()["user_id"] == u["user_id"]


# ============================================================
# Tables CRUD
# ============================================================

def _create_table(token, name=None, **overrides):
    body = {
        "name": name or _name("Room"),
        "target_score": 30,
        "stake": 100,
        "max_players": 2,
        "min_players": 2,
    }
    body.update(overrides)
    r = requests.post(
        f"{API}/v2/lobby/tables", headers=_h(token), json=body, timeout=TIMEOUT,
    )
    return r


class TestTablesCRUD:
    def test_create_table_auto_joins_creator(self):
        u = _auth(_name("creator"))
        r = _create_table(u["token"])
        assert r.status_code == 201, r.text
        t = r.json()
        assert t["status"] == "LOBBY"
        assert t["creator_user_id"] == u["user_id"]
        assert len(t["seats"]) == 1
        assert t["seats"][0]["user_id"] == u["user_id"]
        assert t["target_score"] == 30

    def test_list_tables_includes_created(self):
        u = _auth(_name("lister"))
        t = _create_table(u["token"]).json()
        r = requests.get(f"{API}/v2/lobby/tables", timeout=TIMEOUT)
        assert r.status_code == 200
        ids = [x["table_id"] for x in r.json()]
        assert t["table_id"] in ids

    def test_invalid_target_score_rejected_at_create(self):
        u = _auth(_name("bad"))
        r = _create_table(u["token"], target_score=21)
        assert r.status_code == 400
        assert "INVALID_TARGET_SCORE" in r.text

    def test_join_other_user(self):
        u1 = _auth(_name("j1"))
        u2 = _auth(_name("j2"))
        t = _create_table(u1["token"], max_players=4).json()
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                          headers=_h(u2["token"]), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        ids = sorted(s["user_id"] for s in r.json()["seats"])
        assert ids == sorted([u1["user_id"], u2["user_id"]])

    def test_join_idempotent(self):
        u1 = _auth(_name("idem"))
        t = _create_table(u1["token"]).json()
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                          headers=_h(u1["token"]), timeout=TIMEOUT)
        assert r.status_code == 200
        assert len(r.json()["seats"]) == 1

    def test_join_full_table_rejected(self):
        u1 = _auth(_name("f1"))
        u2 = _auth(_name("f2"))
        u3 = _auth(_name("f3"))
        t = _create_table(u1["token"], max_players=2).json()
        requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                      headers=_h(u2["token"]), timeout=TIMEOUT)
        r3 = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                           headers=_h(u3["token"]), timeout=TIMEOUT)
        assert r3.status_code == 400
        assert "TABLE_FULL" in r3.text

    def test_leave_table(self):
        u1 = _auth(_name("l1"))
        u2 = _auth(_name("l2"))
        t = _create_table(u1["token"], max_players=4).json()
        requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                      headers=_h(u2["token"]), timeout=TIMEOUT)
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/leave",
                          headers=_h(u2["token"]), timeout=TIMEOUT)
        assert r.status_code == 200
        assert all(s["user_id"] != u2["user_id"] for s in r.json()["seats"])


# ============================================================
# Start lifecycle
# ============================================================

class TestStartLifecycle:
    def test_only_creator_can_start(self):
        u1 = _auth(_name("s1"))
        u2 = _auth(_name("s2"))
        t = _create_table(u1["token"]).json()
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/start",
                          headers=_h(u2["token"]), timeout=TIMEOUT)
        assert r.status_code == 403

    def test_start_marks_running(self):
        u1 = _auth(_name("r1"))
        u2 = _auth(_name("r2"))
        t = _create_table(u1["token"]).json()
        requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                      headers=_h(u2["token"]), timeout=TIMEOUT)
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/start",
                          headers=_h(u1["token"]), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "RUNNING"

    def test_join_after_start_rejected(self):
        u1 = _auth(_name("as1"))
        u2 = _auth(_name("as2"))
        u3 = _auth(_name("as3"))
        t = _create_table(u1["token"], max_players=4).json()
        requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                      headers=_h(u2["token"]), timeout=TIMEOUT)
        requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/start",
                      headers=_h(u1["token"]), timeout=TIMEOUT)
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                          headers=_h(u3["token"]), timeout=TIMEOUT)
        assert r.status_code == 400
        assert "TABLE_NOT_JOINABLE" in r.text

    def test_solo_start_includes_bot_in_engine(self):
        """When 1 human is at the table, start spawns a bot so 2-player game runs."""
        u1 = _auth(_name("solo"))
        t = _create_table(u1["token"]).json()
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/start",
                          headers=_h(u1["token"]), timeout=TIMEOUT)
        assert r.status_code == 200

        # Verify by connecting via WS — STATE_UPDATE shows 2 players.
        url = f"{WS_BASE}/api/v2/ws/table/{t['table_id']}?token={u1['token']}"
        with ws_connect(url, open_timeout=10, close_timeout=5) as ws:
            seen_two_players = False
            for _ in range(10):
                import json
                m = json.loads(ws.recv(timeout=5))
                if m.get("type") == "PING":
                    ws.send(json.dumps({"type": "PONG"}))
                    continue
                if m.get("type") == "STATE_UPDATE":
                    assert len(m["players"]) == 2
                    bots = [p for p in m["players"] if p["user_id"].startswith("u_bot_")]
                    assert len(bots) == 1
                    seen_two_players = True
                    break
            assert seen_two_players


# ============================================================
# End-to-end: two real users connect via WS to the same table
# ============================================================

class TestTwoUserE2E:
    def test_two_real_users_both_get_betting_r1_state(self):
        u1 = _auth(_name("e1"))
        u2 = _auth(_name("e2"))
        t = _create_table(u1["token"]).json()
        requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                      headers=_h(u2["token"]), timeout=TIMEOUT)
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/start",
                          headers=_h(u1["token"]), timeout=TIMEOUT)
        assert r.status_code == 200, r.text

        import json
        urls = [
            (u1, f"{WS_BASE}/api/v2/ws/table/{t['table_id']}?token={u1['token']}"),
            (u2, f"{WS_BASE}/api/v2/ws/table/{t['table_id']}?token={u2['token']}"),
        ]
        for u, url in urls:
            with ws_connect(url, open_timeout=10, close_timeout=5) as ws:
                got_state = False
                got_my_private = False
                for _ in range(15):
                    m = json.loads(ws.recv(timeout=5))
                    if m.get("type") == "PING":
                        ws.send(json.dumps({"type": "PONG"}))
                        continue
                    if m.get("type") == "WELCOME":
                        assert m["user_id"] == u["user_id"]
                        continue
                    if m.get("type") == "STATE_UPDATE":
                        assert m["target_score"] == 30
                        assert len(m["players"]) == 2
                        # Both should be human users (no bot).
                        ids = [p["user_id"] for p in m["players"]]
                        assert u1["user_id"] in ids
                        assert u2["user_id"] in ids
                        got_state = True
                    if m.get("type") == "PRIVATE_STATE":
                        assert m["user_id"] == u["user_id"]
                        got_my_private = True
                    if got_state and got_my_private:
                        break
                assert got_state, f"no STATE_UPDATE for {u['user_id']}"
                assert got_my_private, f"no PRIVATE_STATE for {u['user_id']}"
