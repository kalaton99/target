"""Phase 11 P2 — Lobby HTTP + integration tests (live backend).

These tests hit the running supervisor-managed backend (REACT_APP_BACKEND_URL)
to avoid the motor/asyncio event-loop binding issues that occur when using
FastAPI TestClient with module-scope mongo clients.

Covers:
  - guest auth idempotency (same username -> same user_id)
  - invalid username rejected
  - create / list / join / leave / start
  - join idempotency
  - per-target seat-cap enforcement (2026-05 locked-rules migration)
  - non-creator can't START
  - START transitions to RUNNING
  - end-to-end: 2 real users connect via WS to the same table
  - solo creator START with explicit bot_count=1 spawns a bot
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests
from websockets.sync.client import connect as ws_connect

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://gracious-raman-3.preview.emergentagent.com",
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


def _allow_bots() -> bool:
    """Read /api/v2/lobby/config to decide whether bot-dependent
    tests should run. Production deploys advertise allow_bots=False
    and the corresponding tests skip cleanly there."""
    try:
        r = requests.get(f"{API}/v2/lobby/config", timeout=TIMEOUT)
        return bool(r.json().get("allow_bots"))
    except Exception:
        return False


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
# Lobby config (2026-05 locked-rules migration)
# ============================================================

class TestLobbyConfig:
    def test_config_exposes_seat_table_and_bot_flag(self):
        r = requests.get(f"{API}/v2/lobby/config", timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        cfg = r.json()
        # Seat table is a hard contract — production must always
        # advertise these locked-in values.
        seats = cfg["table_seats_by_target"]
        # JSON keys are strings; accept either.
        assert int(seats.get("30", seats.get(30))) == 4
        assert int(seats.get("50", seats.get(50))) == 4
        assert int(seats.get("75", seats.get(75))) == 5
        assert int(seats.get("100", seats.get(100))) == 5
        # Target 250 removed in 2026-05 v2 — must NOT appear.
        assert "250" not in seats and 250 not in seats
        assert isinstance(cfg["allow_bots"], bool)
        assert isinstance(cfg["bot_count_max"], int)

    def test_config_exposes_per_target_bot_cap(self):
        """Per-target bot ceiling (seats - 1). Used by the frontend
        to set `<input max>` dynamically when the target select changes."""
        r = requests.get(f"{API}/v2/lobby/config", timeout=TIMEOUT)
        cfg = r.json()
        assert "bot_count_max_by_target" in cfg, cfg
        per = cfg["bot_count_max_by_target"]

        def _n(k):
            return int(per.get(str(k), per.get(k, -1)))
        if cfg["allow_bots"]:
            assert _n(30) == 3
            assert _n(50) == 3
            assert _n(75) == 4
            assert _n(100) == 4
        else:
            # Production (ALLOW_BOTS=false) must advertise zero bots
            # everywhere so the UI can hide the control.
            for k in (30, 50, 75, 100):
                assert _n(k) == 0


# ============================================================
# Tables CRUD
# ============================================================

def _create_table(token, name=None, **overrides):
    body = {
        "name": name or _name("Room"),
        "target_score": 30,
        "stake": 100,
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
        # Server-derived seat cap (locked rule): target 30 → 4 seats.
        assert t["max_players"] == 4
        assert t["min_players"] == 2

    def test_create_table_target_75_has_5_seats(self):
        u = _auth(_name("t75"))
        t = _create_table(u["token"], target_score=75).json()
        assert t["max_players"] == 5

    def test_create_table_target_100_has_5_seats(self):
        u = _auth(_name("t100"))
        t = _create_table(u["token"], target_score=100).json()
        assert t["max_players"] == 5

    def test_create_table_target_250_rejected_globally(self):
        # 2026-05 v2: target 250 was removed. Server must now reject it.
        u = _auth(_name("t250"))
        r = _create_table(u["token"], target_score=250)
        assert r.status_code == 400
        assert "INVALID_TARGET_SCORE" in r.text

    def test_create_table_ignores_client_supplied_max_players(self):
        # Older clients still send max_players=8; server must ignore it
        # and derive from target_score (locked-rules migration).
        u = _auth(_name("legacy"))
        r = _create_table(u["token"], target_score=30, max_players=8, min_players=2)
        assert r.status_code == 201, r.text
        t = r.json()
        assert t["max_players"] == 4  # NOT 8

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
        t = _create_table(u1["token"], target_score=30).json()  # 4 seats
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
        # Target 30 → 4 seats. Fill all 4, then a 5th join must be rejected.
        creator = _auth(_name("f0"))
        t = _create_table(creator["token"], target_score=30).json()
        for i in range(1, 4):
            u = _auth(_name(f"f{i}"))
            r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                              headers=_h(u["token"]), timeout=TIMEOUT)
            assert r.status_code == 200, r.text
        u_extra = _auth(_name("f5"))
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                          headers=_h(u_extra["token"]), timeout=TIMEOUT)
        assert r.status_code == 400
        assert "TABLE_FULL" in r.text

    def test_leave_table(self):
        u1 = _auth(_name("l1"))
        u2 = _auth(_name("l2"))
        t = _create_table(u1["token"], target_score=30).json()
        requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                      headers=_h(u2["token"]), timeout=TIMEOUT)
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/leave",
                          headers=_h(u2["token"]), timeout=TIMEOUT)
        assert r.status_code == 200
        assert all(s["user_id"] != u2["user_id"] for s in r.json()["seats"])


# ============================================================
# Bot config gate (2026-05 locked-rules migration)
# ============================================================

class TestBotsGated:
    def test_bot_count_zero_always_allowed(self):
        u = _auth(_name("nb"))
        r = _create_table(u["token"], bot_count=0)
        assert r.status_code == 201, r.text

    def test_bot_count_positive_requires_allow_bots(self):
        # In environments where ALLOW_BOTS is True (dev/preview), the
        # request succeeds. In production it is a 400.
        u = _auth(_name("withbot"))
        r = _create_table(u["token"], bot_count=1)
        if _allow_bots():
            assert r.status_code == 201, r.text
            assert r.json().get("bot_count", 0) == 1
        else:
            assert r.status_code == 400
            assert "BOTS_DISABLED" in r.text

    def test_target30_allows_up_to_three_bots(self):
        # 4-seat table: creator + 3 bots = 4 seats filled. 4 bots is
        # rejected at the per-target cap (would leave 0 human seats).
        if not _allow_bots():
            pytest.skip("bots disabled on this server")
        u = _auth(_name("t30b3"))
        r = _create_table(u["token"], target_score=30, bot_count=3)
        assert r.status_code == 201, r.text
        assert r.json().get("bot_count") == 3

    def test_target30_rejects_four_bots(self):
        if not _allow_bots():
            pytest.skip("bots disabled on this server")
        u = _auth(_name("t30b4"))
        r = _create_table(u["token"], target_score=30, bot_count=4)
        assert r.status_code == 400, r.text
        assert "BOT_COUNT_EXCEEDED" in r.text

    def test_target75_allows_up_to_four_bots(self):
        # 5-seat table: creator + 4 bots = 5 seats filled.
        if not _allow_bots():
            pytest.skip("bots disabled on this server")
        u = _auth(_name("t75b4"))
        r = _create_table(u["token"], target_score=75, bot_count=4)
        assert r.status_code == 201, r.text
        assert r.json().get("bot_count") == 4

    def test_target100_allows_up_to_four_bots(self):
        # 5-seat table: creator + 4 bots = 5 seats filled.
        if not _allow_bots():
            pytest.skip("bots disabled on this server")
        u = _auth(_name("t100b4"))
        r = _create_table(u["token"], target_score=100, bot_count=4)
        assert r.status_code == 201, r.text
        assert r.json().get("bot_count") == 4

    def test_bot_count_above_global_ceiling_rejected(self):
        # Pydantic-level guard at le=4 — server must reject 5+ regardless
        # of target. 422 from Pydantic / 400 if overridden.
        u = _auth(_name("gc"))
        r = _create_table(u["token"], target_score=100, bot_count=5)
        assert r.status_code in (400, 422), r.text


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
        t = _create_table(u1["token"], target_score=30).json()
        requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                      headers=_h(u2["token"]), timeout=TIMEOUT)
        requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/start",
                      headers=_h(u1["token"]), timeout=TIMEOUT)
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/join",
                          headers=_h(u3["token"]), timeout=TIMEOUT)
        assert r.status_code == 400
        assert "TABLE_NOT_JOINABLE" in r.text

    def test_solo_start_with_bot_count_seats_a_bot(self):
        """When 1 human creates a table with bot_count=1, START spawns a
        bot so a hand runs with 2 seated players (the minimum legal
        start for the 4-seat tier per GAME_RULES_LOCKED.md §2 — there
        is no 2-seat table type). Skips on production (allow_bots=False)."""
        if not _allow_bots():
            pytest.skip("bots disabled on this server (ALLOW_BOTS=False)")
        u1 = _auth(_name("solo"))
        t = _create_table(u1["token"], bot_count=1).json()
        assert t.get("bot_count") == 1
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/start",
                          headers=_h(u1["token"]), timeout=TIMEOUT)
        assert r.status_code == 200

        # Verify by connecting via WS — STATE_UPDATE shows 2 seated players.
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

    def test_solo_start_without_bot_count_does_not_seat_bot(self):
        """Locked-rules migration: the old 'auto-bot if alone' shortcut
        is removed. Solo start with bot_count=0 produces an engine
        with only the creator seated.

        Note: per GAME_RULES_LOCKED.md §2 a hand cannot legitimately
        run on a 4-seat tier with only 1 seated player (min seated to
        start is 2). This test pins existing dev/CI behaviour where the
        start endpoint currently does not enforce the per-tier minimum
        — kept as-is to avoid coupling this wording-only doc pass to a
        gameplay-validation change."""
        u1 = _auth(_name("alone"))
        t = _create_table(u1["token"]).json()
        assert t.get("bot_count", 0) == 0
        r = requests.post(f"{API}/v2/lobby/tables/{t['table_id']}/start",
                          headers=_h(u1["token"]), timeout=TIMEOUT)
        assert r.status_code == 200

        url = f"{WS_BASE}/api/v2/ws/table/{t['table_id']}?token={u1['token']}"
        with ws_connect(url, open_timeout=10, close_timeout=5) as ws:
            for _ in range(10):
                import json
                m = json.loads(ws.recv(timeout=5))
                if m.get("type") == "PING":
                    ws.send(json.dumps({"type": "PONG"}))
                    continue
                if m.get("type") == "STATE_UPDATE":
                    # No bots seated. Only the creator.
                    assert len(m["players"]) == 1
                    bots = [p for p in m["players"] if p["user_id"].startswith("u_bot_")]
                    assert len(bots) == 0
                    return
            pytest.fail("never observed STATE_UPDATE")


# ============================================================
# End-to-end: two real users connect via WS to the same table
# ============================================================

class TestTwoUserE2E:
    def test_two_real_users_both_get_betting_r1_state(self):
        """After /start returns, the engine MUST already be in BETTING_R1.

        This guards against a previous async-race regression where
        `/start` returned before the engine processed START_HAND,
        causing WS clients connecting immediately after to snapshot
        the engine in WAITING phase. The fix is in
        `realtime_v2/bridge.EngineBridge.submit_server_intent` —
        `_spawn_engine_for_table` now awaits the START_HAND completion
        future before HTTP returns. We assert phase=BETTING_R1 +
        state_version>=1 here to lock the contract in.
        """
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
                # First STATE_UPDATE must already reflect BETTING_R1 with
                # state_version >= 1 — proves /start awaited engine
                # processing.
                first_state_phase = None
                first_state_version = None
                for _ in range(15):
                    m = json.loads(ws.recv(timeout=5))
                    if m.get("type") == "PING":
                        ws.send(json.dumps({"type": "PONG"}))
                        continue
                    if m.get("type") == "WELCOME":
                        assert m["user_id"] == u["user_id"]
                        # WELCOME's state_version must already be >= 1.
                        assert m.get("state_version", 0) >= 1, (
                            f"WELCOME state_version={m.get('state_version')} "
                            "but engine was supposed to have processed START_HAND"
                        )
                        continue
                    if m.get("type") == "STATE_UPDATE":
                        assert m["target_score"] == 30
                        assert len(m["players"]) == 2
                        # Both should be human users (no bot).
                        ids = [p["user_id"] for p in m["players"]]
                        assert u1["user_id"] in ids
                        assert u2["user_id"] in ids
                        if first_state_phase is None:
                            first_state_phase = m["phase"]
                            first_state_version = m["state_version"]
                        got_state = True
                    if m.get("type") == "PRIVATE_STATE":
                        assert m["user_id"] == u["user_id"]
                        got_my_private = True
                    if got_state and got_my_private:
                        break
                assert got_state, f"no STATE_UPDATE for {u['user_id']}"
                assert got_my_private, f"no PRIVATE_STATE for {u['user_id']}"
                # Determinism contract: by the time the client connects,
                # the engine MUST have transitioned to BETTING_R1.
                assert first_state_phase == "BETTING_R1", (
                    f"first STATE_UPDATE phase={first_state_phase} for "
                    f"{u['user_id']} — expected BETTING_R1 (race regression)"
                )
                assert first_state_version >= 1, (
                    f"first STATE_UPDATE state_version={first_state_version}"
                )
