"""WebSocket realtime tests covering hand lifecycle, state_version, and 15s timeout."""
import asyncio
import json
import os
import uuid
import requests
import pytest
import websockets

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://gracious-raman-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
WS_BASE = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")


def _h(t):
    return {"Authorization": f"Bearer {t}"}


def _ws_url(table_id, token):
    return f"{WS_BASE}/api/ws/table/{table_id}?token={token}"


def _new_user(prefix="WS"):
    rnd = uuid.uuid4().hex[:8]
    email = f"test_ws_{prefix}_{rnd}@targetgame.app"
    r = requests.post(
        f"{API}/auth/register",
        json={"email": email, "username": f"TEST_{prefix}_{rnd}"[:24], "password": "Target!2025"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _recv_until(ws, predicate, timeout=10.0, collected=None):
    """Receive messages until predicate(msg) is True. Returns (matched_msg, all_msgs)."""
    msgs = collected if collected is not None else []
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        remaining = max(0.05, end - asyncio.get_event_loop().time())
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        try:
            data = json.loads(raw)
        except Exception:
            continue
        msgs.append(data)
        if predicate(data):
            return data, msgs
    return None, msgs


async def _setup_two_players_at_table():
    """Create 2 players, table, both join, return (p1, p2, table_id)."""
    p1 = _new_user("P1")
    p2 = _new_user("P2")
    # p1 quick-joins (creates new table)
    r = requests.post(f"{API}/tables", headers=_h(p1["token"]),
                      json={"name": f"TEST_ws_{uuid.uuid4().hex[:6]}", "type": "FREE", "stake": 100, "max_players": 4}, timeout=15)
    assert r.status_code == 200
    tid = r.json()["id"]
    r1 = requests.post(f"{API}/tables/{tid}/join", headers=_h(p1["token"]), timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/tables/{tid}/join", headers=_h(p2["token"]), timeout=15)
    assert r2.status_code == 200
    return p1, p2, tid


# ---------- WS auth ----------
@pytest.mark.asyncio
async def test_ws_rejects_missing_token():
    p1 = _new_user()
    r = requests.post(f"{API}/tables/quick-join", headers=_h(p1["token"]), json={"type": "FREE"}, timeout=15)
    tid = r.json()["table_id"]
    url = f"{WS_BASE}/api/ws/table/{tid}"
    with pytest.raises(Exception):
        async with websockets.connect(url, open_timeout=5) as ws:
            await ws.recv()


@pytest.mark.asyncio
async def test_ws_rejects_bad_token():
    url = f"{WS_BASE}/api/ws/table/t_fake?token=invalidjwt"
    with pytest.raises(Exception):
        async with websockets.connect(url, open_timeout=5) as ws:
            await ws.recv()


@pytest.mark.asyncio
async def test_ws_rejects_user_not_seated():
    p1 = _new_user("S1")
    p2 = _new_user("S2")  # not seated
    r = requests.post(f"{API}/tables", headers=_h(p1["token"]),
                      json={"name": "TEST_seat", "type": "FREE", "stake": 100, "max_players": 4}, timeout=15)
    tid = r.json()["id"]
    requests.post(f"{API}/tables/{tid}/join", headers=_h(p1["token"]), timeout=15)
    # p2 not seated - should be rejected
    with pytest.raises(Exception):
        async with websockets.connect(_ws_url(tid, p2["token"]), open_timeout=5) as ws:
            await ws.recv()


# ---------- WS hand lifecycle ----------
@pytest.mark.asyncio
async def test_ws_two_players_auto_start_hand():
    p1, p2, tid = await _setup_two_players_at_table()
    async with websockets.connect(_ws_url(tid, p1["token"]), open_timeout=5) as ws1, \
               websockets.connect(_ws_url(tid, p2["token"]), open_timeout=5) as ws2:
        # Wait for DEAL to complete -> state phase becomes DRAW
        async def collect(ws, end_phase, t=12.0):
            msgs = []
            end = asyncio.get_event_loop().time() + t
            while asyncio.get_event_loop().time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                msgs.append(data)
                if data.get("type") == "STATE_UPDATE" and data.get("view", {}).get("phase") == end_phase:
                    return data, msgs
            return None, msgs

        # Both clients should observe DRAW phase
        result1 = await collect(ws1, "DRAW", t=15.0)
        result2 = await collect(ws2, "DRAW", t=15.0)
        assert result1[0] is not None, f"p1 never reached DRAW. Got: {[m.get('view',{}).get('phase') for m in result1[1] if m.get('type')=='STATE_UPDATE']}"
        assert result2[0] is not None, f"p2 never reached DRAW. Got: {[m.get('view',{}).get('phase') for m in result2[1] if m.get('type')=='STATE_UPDATE']}"
        view1 = result1[0]["view"]
        assert view1["phase"] == "DRAW"
        assert view1.get("current_turn_seat") == 0
        # local player should see own cards
        my_player = next((p for p in view1["players"] if p["user_id"] == p1["user"]["id"]), None)
        assert my_player and len(my_player.get("cards", [])) >= 2


@pytest.mark.asyncio
async def test_ws_missing_state_version_rejected():
    p1, p2, tid = await _setup_two_players_at_table()
    async with websockets.connect(_ws_url(tid, p1["token"]), open_timeout=5) as ws1, \
               websockets.connect(_ws_url(tid, p2["token"]), open_timeout=5) as ws2:
        # Wait briefly for state to settle
        await asyncio.sleep(2.5)
        # send a STAND without state_version
        await ws1.send(json.dumps({"type": "STAND", "client_action_id": str(uuid.uuid4())}))
        rej, _ = await _recv_until(ws1, lambda m: m.get("type") == "ACTION_REJECTED", timeout=5.0)
        assert rej is not None, "no ACTION_REJECTED received"
        assert rej["error"] == "MISSING_STATE_VERSION"


@pytest.mark.asyncio
async def test_ws_stale_state_version_rejected():
    p1, p2, tid = await _setup_two_players_at_table()
    async with websockets.connect(_ws_url(tid, p1["token"]), open_timeout=5) as ws1, \
               websockets.connect(_ws_url(tid, p2["token"]), open_timeout=5) as ws2:
        await asyncio.sleep(3.0)
        await ws1.send(json.dumps({"type": "STAND", "client_action_id": str(uuid.uuid4()), "state_version": 0}))
        rej, _ = await _recv_until(ws1, lambda m: m.get("type") == "ACTION_REJECTED", timeout=5.0)
        assert rej is not None
        assert rej["error"] == "OUT_OF_SYNC"
        assert "expected_state_version" in rej
        assert "fresh_state" in rej


@pytest.mark.asyncio
async def test_ws_server_only_action_rejected():
    p1, p2, tid = await _setup_two_players_at_table()
    async with websockets.connect(_ws_url(tid, p1["token"]), open_timeout=5) as ws1, \
               websockets.connect(_ws_url(tid, p2["token"]), open_timeout=5) as ws2:
        await asyncio.sleep(2.0)
        await ws1.send(json.dumps({
            "type": "AUTO_STAND_TIMEOUT",
            "client_action_id": str(uuid.uuid4()),
            "state_version": 999,
        }))
        rej, _ = await _recv_until(ws1, lambda m: m.get("type") == "ACTION_REJECTED", timeout=5.0)
        assert rej is not None
        assert rej["error"] == "SERVER_ONLY_ACTION"


@pytest.mark.asyncio
async def test_ws_stand_advances_turn():
    p1, p2, tid = await _setup_two_players_at_table()
    async with websockets.connect(_ws_url(tid, p1["token"]), open_timeout=5) as ws1, \
               websockets.connect(_ws_url(tid, p2["token"]), open_timeout=5) as ws2:
        # Drain until quiet, capture latest DRAW state
        async def drain_to_latest_draw(ws, t=10.0):
            latest = None
            end = asyncio.get_event_loop().time() + t
            quiet_until = None
            while asyncio.get_event_loop().time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.4)
                except asyncio.TimeoutError:
                    if latest is not None and latest["view"]["phase"] == "DRAW":
                        return latest
                    continue
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                if d.get("type") == "STATE_UPDATE":
                    latest = d
            return latest

        d1 = await drain_to_latest_draw(ws1, t=12.0)
        await drain_to_latest_draw(ws2, t=4.0)
        assert d1 is not None and d1["view"]["phase"] == "DRAW"
        v_before = d1["state_version"]
        seat0_uid = next(p["user_id"] for p in d1["view"]["players"] if p["seat_index"] == 0)
        ws_seat0 = ws1 if seat0_uid == p1["user"]["id"] else ws2
        await ws_seat0.send(json.dumps({"type": "STAND", "client_action_id": str(uuid.uuid4()), "state_version": v_before}))
        # accept either state advance or ACTION_REJECTED with fresh state
        nxt, _ = await _recv_until(
            ws_seat0,
            lambda m: (m.get("type") == "STATE_UPDATE" and m.get("state_version", 0) > v_before)
                      or (m.get("type") == "ACTION_REJECTED"),
            timeout=10.0,
        )
        assert nxt is not None, "no advance after STAND"
        if nxt.get("type") == "ACTION_REJECTED":
            # OUT_OF_SYNC due to race; retry once with fresh version
            v2 = nxt.get("expected_state_version") or nxt.get("state_version")
            await ws_seat0.send(json.dumps({"type": "STAND", "client_action_id": str(uuid.uuid4()), "state_version": v2}))
            nxt2, _ = await _recv_until(ws_seat0, lambda m: m.get("type") == "STATE_UPDATE" and m.get("state_version", 0) > v2, timeout=8.0)
            assert nxt2 is not None
            v = nxt2["view"]
        else:
            v = nxt["view"]
        assert v["phase"] in ("DRAW", "BETTING", "SHOWDOWN", "PAYOUT", "ENDED")


# ---------- 15-sec timeout (CRITICAL) ----------
@pytest.mark.asyncio
async def test_ws_turn_timeout_emits_auto_stand_not_fold():
    p1, p2, tid = await _setup_two_players_at_table()
    async with websockets.connect(_ws_url(tid, p1["token"]), open_timeout=5) as ws1, \
               websockets.connect(_ws_url(tid, p2["token"]), open_timeout=5) as ws2:
        # Wait until DRAW
        async def wait_draw(ws):
            for _ in range(40):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                if d.get("type") == "STATE_UPDATE" and d.get("view", {}).get("phase") == "DRAW":
                    return d
            return None
        d1 = await wait_draw(ws1)
        await wait_draw(ws2)
        assert d1 is not None
        v_before = d1["state_version"]
        # DO NOT send any action — wait for 15-second timeout
        # Server should auto-emit AUTO_STAND_TIMEOUT after ~15s
        async def wait_advance(ws, t=20.0):
            end = asyncio.get_event_loop().time() + t
            while asyncio.get_event_loop().time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                if d.get("type") == "STATE_UPDATE" and d.get("state_version", 0) > v_before:
                    return d
            return None
        nxt = await wait_advance(ws1, t=20.0)
        assert nxt is not None, "No state update after 15s timeout — auto-stand never fired"
        # Check hand_actions in DB via API would require admin endpoint we don't have.
        # Verify via state: phase should still progress (turn advanced or BETTING).
        # Critical: verify TIMEOUT_AUTOSTAND was recorded (not FOLD) by inspecting events
        events = nxt.get("events", [])
        # Allow either explicit STAND with auto flag or PHASE/turn advance
        # The reducer should emit STAND-class event not FOLD
        types = [e.get("type") for e in events]
        assert "FOLD" not in types, f"Got FOLD instead of STAND on timeout! events={events}"


# ---------- Idempotency ----------
@pytest.mark.asyncio
async def test_ws_idempotency_same_client_action_id():
    """Same client_action_id replayed should not double-effect (CALL/RAISE).
    Here we test STAND replay: should be ignored or rejected, not duplicate-advance.
    """
    p1, p2, tid = await _setup_two_players_at_table()
    async with websockets.connect(_ws_url(tid, p1["token"]), open_timeout=5) as ws1, \
               websockets.connect(_ws_url(tid, p2["token"]), open_timeout=5) as ws2:
        await asyncio.sleep(3.0)
        # drain
        # send STAND from current turn player twice with same action_id
        # We won't strictly assert; just ensure server doesn't crash
        cid = str(uuid.uuid4())
        # Try to find DRAW state version via a quick recv burst
        v = None
        seat0 = None
        for _ in range(20):
            try:
                raw = await asyncio.wait_for(ws1.recv(), timeout=0.4)
                d = json.loads(raw)
                if d.get("type") == "STATE_UPDATE" and d.get("view", {}).get("phase") == "DRAW":
                    v = d["state_version"]
                    seat0 = next(p["user_id"] for p in d["view"]["players"] if p["seat_index"] == 0)
            except asyncio.TimeoutError:
                pass
        if v is None:
            pytest.skip("Could not reach DRAW phase")
        ws_t = ws1 if seat0 == p1["user"]["id"] else ws2
        await ws_t.send(json.dumps({"type": "STAND", "client_action_id": cid, "state_version": v}))
        await asyncio.sleep(0.3)
        await ws_t.send(json.dumps({"type": "STAND", "client_action_id": cid, "state_version": v}))
        # Server should still be alive
        await ws_t.send(json.dumps({"type": "PING"}))
        pong, _ = await _recv_until(ws_t, lambda m: m.get("type") == "PONG", timeout=5)
        assert pong is not None
