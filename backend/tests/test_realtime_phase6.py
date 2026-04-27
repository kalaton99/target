"""Phase 6 — Realtime WebSocket gateway tests.

Covers:
  Gatekeeper
    - per-user cap
    - per-IP cap
    - release frees slot
    - release of unknown token is a noop
    - concurrent acquire is atomic (no overshoot)

  PubSub
    - publish delivers to all subscribers of a topic
    - other topics unaffected
    - unsubscribe stops delivery
    - bounded queue drops on full instead of stalling

  Gateway
    - JWT/session bind: bad token → close 1008 + AUTH_FAILED
    - JWT/session bind: good token → WELCOME with state_version
    - per-user cap exceeded → close 1008
    - per-IP cap exceeded → close 1008
    - valid action with matching state_version → ACTION_ACK + handler invoked
    - missing state_version → ERROR (session stays open)
    - stale state_version → OUT_OF_SYNC (session stays open, handler NOT invoked)
    - server-only message type → ERROR + connection closed (security boundary)
    - unknown message type → ERROR but session stays open
    - unknown table_id → ERROR TABLE_NOT_FOUND
    - pubsub broadcast on subscribed topic → delivered to socket
    - pubsub broadcast on different topic → NOT delivered
    - disconnect cleanup: gatekeeper slot released + pubsub unsubscribed
    - heartbeat: no PONG → connection closes
    - heartbeat: client PONGs → connection stays alive
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# Make /app/backend importable without installing as a package.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from realtime_v2 import (  # noqa: E402
    Gatekeeper,
    IpCapExceeded,
    PubSub,
    UserCapExceeded,
    WebSocketGateway,
)


# =====================================================================
# Fake WebSocket transport (asyncio queues, no network).
# =====================================================================

_DISCONNECT = object()


class FakeWebSocket:
    """Implements WebSocketLike using two asyncio queues."""

    def __init__(self) -> None:
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._outbox: asyncio.Queue = asyncio.Queue()
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None

    # ---- WebSocketLike ----

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        if self.closed:
            return
        self.closed = True
        self.close_code = code
        try:
            self._inbox.put_nowait(_DISCONNECT)
        except asyncio.QueueFull:
            pass

    async def send_json(self, data) -> None:
        if self.closed:
            raise ConnectionError("closed")
        await self._outbox.put(data)

    async def receive_json(self):
        msg = await self._inbox.get()
        if msg is _DISCONNECT:
            raise ConnectionError("disconnected")
        return msg

    # ---- test helpers (drive the connection from the "client" side) ----

    async def client_send(self, msg) -> None:
        await self._inbox.put(msg)

    async def client_recv(self, timeout: float = 2.0):
        return await asyncio.wait_for(self._outbox.get(), timeout)

    async def client_disconnect(self) -> None:
        await self._inbox.put(_DISCONNECT)


# =====================================================================
# Injected callable fakes.
# =====================================================================

VALID_TOKENS = {
    "tok-alice": "alice",
    "tok-bob": "bob",
    "tok-carol": "carol",
}


async def fake_authenticate(token: str):
    return VALID_TOKENS.get(token)


def make_state_version_provider(versions: dict):
    async def _provider(table_id: str):
        return versions.get(table_id)
    return _provider


def make_action_handler(record: list, result: dict | None = None):
    async def _handler(table_id, user_id, action, payload, sv):
        record.append({
            "table_id": table_id, "user_id": user_id,
            "action": action, "payload": payload, "sv": sv,
        })
        return dict(result) if result else {"ok": True}
    return _handler


def make_gateway(
    *,
    gk: Gatekeeper | None = None,
    ps: PubSub | None = None,
    versions: dict | None = None,
    action_record: list | None = None,
    action_result: dict | None = None,
    ping_interval: float = 10.0,
    ping_timeout: float = 10.0,
):
    gk = gk or Gatekeeper(max_per_user=2, max_per_ip=8)
    ps = ps or PubSub()
    versions = {"t1": 5} if versions is None else versions
    record = [] if action_record is None else action_record
    return (
        WebSocketGateway(
            gatekeeper=gk,
            pubsub=ps,
            authenticate=fake_authenticate,
            get_state_version=make_state_version_provider(versions),
            handle_action=make_action_handler(record, action_result),
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
        ),
        gk,
        ps,
        record,
    )


async def _start(gw, ws, *, token="tok-alice", table_id="t1", ip="1.1.1.1"):
    return asyncio.create_task(
        gw.handle(ws, token=token, table_id=table_id, ip=ip),
    )


# =====================================================================
# Gatekeeper
# =====================================================================

class TestGatekeeper:

    async def test_acquire_under_user_cap(self):
        gk = Gatekeeper(max_per_user=2, max_per_ip=10)
        await gk.acquire("alice", "1.1.1.1")
        await gk.acquire("alice", "1.1.1.2")
        assert gk.user_count("alice") == 2
        assert gk.total() == 2

    async def test_user_cap_exceeded(self):
        gk = Gatekeeper(max_per_user=2, max_per_ip=10)
        await gk.acquire("alice", "1.1.1.1")
        await gk.acquire("alice", "1.1.1.2")
        with pytest.raises(UserCapExceeded):
            await gk.acquire("alice", "1.1.1.3")

    async def test_ip_cap_exceeded(self):
        gk = Gatekeeper(max_per_user=10, max_per_ip=2)
        await gk.acquire("alice", "9.9.9.9")
        await gk.acquire("bob", "9.9.9.9")
        with pytest.raises(IpCapExceeded):
            await gk.acquire("carol", "9.9.9.9")

    async def test_release_frees_slot(self):
        gk = Gatekeeper(max_per_user=1, max_per_ip=10)
        token = await gk.acquire("alice", "1.1.1.1")
        with pytest.raises(UserCapExceeded):
            await gk.acquire("alice", "1.1.1.1")
        await gk.release(token)
        assert gk.user_count("alice") == 0
        # slot freed → succeeds
        await gk.acquire("alice", "1.1.1.1")

    async def test_release_unknown_token_noop(self):
        gk = Gatekeeper()
        await gk.release("does-not-exist")  # must not raise
        assert gk.total() == 0

    async def test_concurrent_acquire_respects_cap(self):
        """Cap=3, fire 8 concurrent acquires — exactly 3 succeed, 5 fail."""
        gk = Gatekeeper(max_per_user=3, max_per_ip=100)

        async def go(i):
            try:
                return await gk.acquire("alice", f"ip-{i}")
            except UserCapExceeded:
                return "ERR"

        results = await asyncio.gather(*[go(i) for i in range(8)])
        oks = [r for r in results if r != "ERR"]
        errs = [r for r in results if r == "ERR"]
        assert len(oks) == 3
        assert len(errs) == 5
        assert gk.user_count("alice") == 3


# =====================================================================
# PubSub
# =====================================================================

class TestPubSub:

    async def test_publish_to_all_subscribers(self):
        ps = PubSub()
        q1 = await ps.subscribe("table:1")
        q2 = await ps.subscribe("table:1")
        n = await ps.publish("table:1", {"x": 1})
        assert n == 2
        assert q1.get_nowait() == {"x": 1}
        assert q2.get_nowait() == {"x": 1}

    async def test_other_topics_isolated(self):
        ps = PubSub()
        q1 = await ps.subscribe("table:1")
        q2 = await ps.subscribe("table:2")
        await ps.publish("table:1", {"x": 1})
        assert q1.qsize() == 1
        assert q2.qsize() == 0

    async def test_unsubscribe_stops_delivery(self):
        ps = PubSub()
        q = await ps.subscribe("t")
        assert ps.subscriber_count("t") == 1
        await ps.unsubscribe("t", q)
        assert ps.subscriber_count("t") == 0
        n = await ps.publish("t", {"x": 1})
        assert n == 0

    async def test_bounded_queue_drops_on_full(self):
        ps = PubSub(queue_max=2)
        await ps.subscribe("t")
        await ps.publish("t", 1)
        await ps.publish("t", 2)
        n = await ps.publish("t", 3)
        # 3rd publish: queue full → 0 delivered + 1 drop
        assert n == 0
        assert ps.drops == 1


# =====================================================================
# Gateway — auth / session bind
# =====================================================================

class TestGatewayAuth:

    async def test_bad_token_closes_1008(self):
        gw, gk, _, _ = make_gateway()
        ws = FakeWebSocket()
        task = await _start(gw, ws, token="invalid")
        await asyncio.wait_for(task, timeout=2)
        msg = ws._outbox.get_nowait()
        assert msg["type"] == "ERROR"
        assert msg["code"] == "AUTH_FAILED"
        assert ws.closed and ws.close_code == 1008
        assert gk.total() == 0  # no slot consumed for bad token

    async def test_good_token_welcome_with_state_version(self):
        gw, gk, _, _ = make_gateway(versions={"t1": 42})
        ws = FakeWebSocket()
        task = await _start(gw, ws, token="tok-alice", table_id="t1")
        msg = await ws.client_recv()
        assert msg["type"] == "WELCOME"
        assert msg["user_id"] == "alice"
        assert msg["table_id"] == "t1"
        assert msg["state_version"] == 42
        assert gk.total() == 1
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)
        assert gk.total() == 0


# =====================================================================
# Gateway — connection caps
# =====================================================================

class TestGatewayCaps:

    async def test_user_cap_rejected_at_gateway(self):
        gk = Gatekeeper(max_per_user=1, max_per_ip=10)
        gw, _, _, _ = make_gateway(gk=gk)
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        t1 = await _start(gw, ws1, token="tok-alice", ip="1.1.1.1")
        await ws1.client_recv()  # WELCOME
        t2 = await _start(gw, ws2, token="tok-alice", ip="2.2.2.2")
        await asyncio.wait_for(t2, timeout=2)
        msg = ws2._outbox.get_nowait()
        assert msg["type"] == "ERROR" and msg["code"] == "USER_CAP_EXCEEDED"
        assert ws2.closed and ws2.close_code == 1008
        await ws1.client_disconnect()
        await asyncio.wait_for(t1, timeout=2)

    async def test_ip_cap_rejected_at_gateway(self):
        gk = Gatekeeper(max_per_user=10, max_per_ip=1)
        gw, _, _, _ = make_gateway(gk=gk)
        ws1, ws2 = FakeWebSocket(), FakeWebSocket()
        t1 = await _start(gw, ws1, token="tok-alice", ip="9.9.9.9")
        await ws1.client_recv()
        t2 = await _start(gw, ws2, token="tok-bob", ip="9.9.9.9")
        await asyncio.wait_for(t2, timeout=2)
        msg = ws2._outbox.get_nowait()
        assert msg["type"] == "ERROR" and msg["code"] == "IP_CAP_EXCEEDED"
        assert ws2.closed and ws2.close_code == 1008
        await ws1.client_disconnect()
        await asyncio.wait_for(t1, timeout=2)


# =====================================================================
# Gateway — action validation & state_version
# =====================================================================

class TestGatewayActions:

    async def test_valid_action_acked(self):
        gw, _, _, record = make_gateway(
            versions={"t1": 5}, action_result={"phase": "DRAW"},
        )
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()  # WELCOME
        await ws.client_send({
            "type": "HIT", "state_version": 5, "payload": {"hand_id": "h1"},
        })
        ack = await ws.client_recv()
        assert ack["type"] == "ACTION_ACK"
        assert ack["action"] == "HIT"
        assert ack["result"] == {"phase": "DRAW"}
        assert len(record) == 1
        assert record[0]["user_id"] == "alice"
        assert record[0]["action"] == "HIT"
        assert record[0]["sv"] == 5
        assert record[0]["payload"] == {"hand_id": "h1"}
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)

    async def test_missing_state_version_rejected(self):
        gw, _, _, record = make_gateway()
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()
        await ws.client_send({"type": "HIT", "payload": {}})
        err = await ws.client_recv()
        assert err["type"] == "ERROR" and err["code"] == "MISSING_STATE_VERSION"
        assert record == []
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)

    async def test_state_version_must_be_int_not_bool(self):
        """Booleans are technically int in Python — explicitly rejected."""
        gw, _, _, record = make_gateway()
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()
        await ws.client_send({"type": "HIT", "state_version": True, "payload": {}})
        err = await ws.client_recv()
        assert err["type"] == "ERROR" and err["code"] == "MISSING_STATE_VERSION"
        assert record == []
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)

    async def test_stale_state_version_emits_out_of_sync(self):
        gw, _, _, record = make_gateway(versions={"t1": 7})
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()
        await ws.client_send({"type": "STAND", "state_version": 3, "payload": {}})
        err = await ws.client_recv()
        assert err["type"] == "OUT_OF_SYNC"
        assert err["received_state_version"] == 3
        assert err["current_state_version"] == 7
        assert record == []
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)

    async def test_server_only_type_closes_connection(self):
        gw, _, _, record = make_gateway()
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()  # WELCOME
        await ws.client_send({"type": "STATE_UPDATE", "state_version": 5})
        err = await ws.client_recv()
        assert err["type"] == "ERROR" and err["code"] == "SERVER_ONLY_TYPE"
        # connection must be closed by the gateway
        await asyncio.wait_for(task, timeout=2)
        assert ws.closed
        assert record == []

    async def test_unknown_type_does_not_close(self):
        gw, _, _, record = make_gateway()
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()
        await ws.client_send({"type": "GIBBERISH", "state_version": 5})
        err = await ws.client_recv()
        assert err["type"] == "ERROR" and err["code"] == "UNKNOWN_TYPE"
        # Session still alive — send a real action.
        await ws.client_send({"type": "HIT", "state_version": 5, "payload": {}})
        ack = await ws.client_recv()
        assert ack["type"] == "ACTION_ACK"
        assert len(record) == 1
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)

    async def test_play_two_and_play_ten_are_accepted_by_gateway(self):
        # Phase 11 P1 — special-card intents must be on the CLIENT_ACTIONS
        # whitelist so the gateway forwards them to the engine. The engine
        # itself enforces phase / turn / hand contents.
        gw, _, _, record = make_gateway()
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()  # WELCOME
        await ws.client_send({
            "type": "PLAY_TWO",
            "state_version": 5,
            "payload": {"target_user_id": "u_other", "transfer_card_index": 0},
        })
        ack1 = await ws.client_recv()
        assert ack1["type"] == "ACTION_ACK"
        assert ack1["action"] == "PLAY_TWO"
        await ws.client_send({
            "type": "PLAY_TEN",
            "state_version": 5,
            "payload": {"target_user_id": "u_other", "attack_card_index": 0},
        })
        ack2 = await ws.client_recv()
        assert ack2["type"] == "ACTION_ACK"
        assert ack2["action"] == "PLAY_TEN"
        # Both intents reached the action handler with their structured payload.
        assert len(record) == 2
        types_seen = [r["action"] for r in record]
        assert "PLAY_TWO" in types_seen and "PLAY_TEN" in types_seen
        # Payload survives the round trip (gateway must not strip it).
        play_two = next(r for r in record if r["action"] == "PLAY_TWO")
        assert play_two["payload"] == {"target_user_id": "u_other", "transfer_card_index": 0}
        play_ten = next(r for r in record if r["action"] == "PLAY_TEN")
        assert play_ten["payload"] == {"target_user_id": "u_other", "attack_card_index": 0}
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)

    async def test_unknown_table_id(self):
        gw, _, _, _ = make_gateway(versions={})
        ws = FakeWebSocket()
        task = await _start(gw, ws, table_id="ghost")
        wm = await ws.client_recv()
        assert wm["type"] == "WELCOME" and wm["state_version"] == 0
        await ws.client_send({"type": "HIT", "state_version": 0, "payload": {}})
        err = await ws.client_recv()
        assert err["type"] == "ERROR" and err["code"] == "TABLE_NOT_FOUND"
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)

    async def test_action_handler_exception_surfaces_as_error(self):
        async def boom(*args, **kwargs):
            raise RuntimeError("engine crashed")

        gw = WebSocketGateway(
            gatekeeper=Gatekeeper(),
            pubsub=PubSub(),
            authenticate=fake_authenticate,
            get_state_version=make_state_version_provider({"t1": 5}),
            handle_action=boom,
            ping_interval=10.0,
            ping_timeout=10.0,
        )
        ws = FakeWebSocket()
        task = asyncio.create_task(
            gw.handle(ws, token="tok-alice", table_id="t1", ip="1.1.1.1"),
        )
        await ws.client_recv()
        await ws.client_send({"type": "HIT", "state_version": 5, "payload": {}})
        err = await ws.client_recv()
        assert err["type"] == "ERROR" and err["code"] == "ACTION_FAILED"
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)


# =====================================================================
# Gateway — pub/sub broadcast bridge
# =====================================================================

class TestGatewayBroadcast:

    async def test_broadcast_delivered_to_socket(self):
        ps = PubSub()
        gw, _, _, _ = make_gateway(ps=ps)
        ws = FakeWebSocket()
        task = await _start(gw, ws, table_id="t1")
        await ws.client_recv()  # WELCOME (subscription is in place by here)
        await ps.publish(
            "table:t1",
            {"type": "STATE_UPDATE", "phase": "DRAW", "state_version": 6},
        )
        msg = await ws.client_recv()
        assert msg["type"] == "STATE_UPDATE"
        assert msg["phase"] == "DRAW"
        assert msg["state_version"] == 6
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)

    async def test_broadcast_isolated_to_subscribed_table(self):
        ps = PubSub()
        gw, _, _, _ = make_gateway(ps=ps, versions={"t1": 5, "t2": 5})
        ws = FakeWebSocket()
        task = await _start(gw, ws, table_id="t1")
        await ws.client_recv()  # WELCOME
        await ps.publish("table:t2", {"type": "STATE_UPDATE"})
        with pytest.raises(asyncio.TimeoutError):
            await ws.client_recv(timeout=0.4)
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)

    async def test_multiple_clients_same_table_all_receive(self):
        ps = PubSub()
        gw, _, _, _ = make_gateway(ps=ps)
        ws_a, ws_b = FakeWebSocket(), FakeWebSocket()
        ta = await _start(gw, ws_a, token="tok-alice", ip="1.1.1.1")
        tb = await _start(gw, ws_b, token="tok-bob", ip="2.2.2.2")
        await ws_a.client_recv()
        await ws_b.client_recv()
        await ps.publish("table:t1", {"type": "PHASE_CHANGED", "phase": "BETTING"})
        ma = await ws_a.client_recv()
        mb = await ws_b.client_recv()
        assert ma["phase"] == "BETTING"
        assert mb["phase"] == "BETTING"
        await ws_a.client_disconnect()
        await ws_b.client_disconnect()
        await asyncio.wait_for(ta, timeout=2)
        await asyncio.wait_for(tb, timeout=2)


# =====================================================================
# Gateway — disconnect cleanup
# =====================================================================

class TestGatewayDisconnect:

    async def test_disconnect_releases_slot_and_unsubscribes(self):
        ps = PubSub()
        gk = Gatekeeper(max_per_user=2, max_per_ip=10)
        gw, _, _, _ = make_gateway(gk=gk, ps=ps)
        ws = FakeWebSocket()
        task = await _start(gw, ws, table_id="t1")
        await ws.client_recv()  # WELCOME
        assert gk.total() == 1
        assert ps.subscriber_count("table:t1") == 1
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)
        assert gk.total() == 0
        assert ps.subscriber_count("table:t1") == 0

    async def test_server_close_path_releases_slot(self):
        gk = Gatekeeper(max_per_user=2, max_per_ip=10)
        gw, _, _, _ = make_gateway(gk=gk)
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()
        assert gk.total() == 1
        # Server-only message triggers gateway-side close.
        await ws.client_send({"type": "STATE_UPDATE", "state_version": 5})
        await ws.client_recv()  # the ERROR
        await asyncio.wait_for(task, timeout=2)
        assert gk.total() == 0


# =====================================================================
# Gateway — ping/pong heartbeat
# =====================================================================

class TestGatewayHeartbeat:

    async def test_no_pong_closes_connection(self):
        gw, gk, _, _ = make_gateway(ping_interval=0.05, ping_timeout=0.05)
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()  # WELCOME
        # Never send PONG — heartbeat must close within ~0.5s.
        await asyncio.wait_for(task, timeout=2.0)
        assert gk.total() == 0
        assert ws.closed

    async def test_pong_keeps_connection_alive(self):
        gw, gk, _, _ = make_gateway(ping_interval=0.1, ping_timeout=0.1)
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()  # WELCOME
        # Pong-pump for ~0.7s; connection must remain open.
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 0.7
        pings_seen = 0
        while loop.time() < deadline:
            try:
                m = await ws.client_recv(timeout=0.15)
                if m.get("type") == "PING":
                    pings_seen += 1
                    await ws.client_send({"type": "PONG"})
            except asyncio.TimeoutError:
                pass
        assert pings_seen >= 2
        assert not task.done()
        assert gk.total() == 1
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)


# =====================================================================
# Gateway — bad-shape resilience
# =====================================================================

class TestGatewayBadShape:

    async def test_non_dict_message_closes(self):
        gw, gk, _, _ = make_gateway()
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()  # WELCOME
        await ws.client_send("not-a-dict")
        err = await ws.client_recv()
        assert err["type"] == "ERROR" and err["code"] == "BAD_MESSAGE"
        await asyncio.wait_for(task, timeout=2)
        assert gk.total() == 0

    async def test_non_dict_payload_rejected(self):
        gw, _, _, record = make_gateway()
        ws = FakeWebSocket()
        task = await _start(gw, ws)
        await ws.client_recv()
        await ws.client_send({
            "type": "BET", "state_version": 5, "payload": "string-not-dict",
        })
        err = await ws.client_recv()
        assert err["type"] == "ERROR" and err["code"] == "BAD_PAYLOAD"
        assert record == []
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)
