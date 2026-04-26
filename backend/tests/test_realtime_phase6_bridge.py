"""Phase 6 — Engine ↔ Realtime bridge tests.

End-to-end coverage of the full Phase 6 pipeline:
  client intent → gateway → bridge → engine → on_event → pubsub → subscribers

Cases:
  - bridge return value:
      * unknown table → TABLE_NOT_FOUND
      * stale state_version → engine reject OUT_OF_SYNC (NO broadcast)
      * valid action → accepted + state_version returned
      * non-current player STAND → engine reject NOT_YOUR_TURN (NO broadcast)
  - broadcast envelope:
      * single client action results in exactly one STATE_UPDATE published
      * STATE_UPDATE contains state_version, phase, players, events
      * cards face-down for everyone in broadcast (privacy)
  - multi-subscriber:
      * two pubsub subscribers both receive same STATE_UPDATE
  - state_version monotonic propagation:
      * two sequential actions → two STATE_UPDATEs with version N, N+1
  - timeout → broadcast:
      * AUTO_STAND_TIMEOUT fires from engine timer → STATE_UPDATE published
      * the broadcast has events containing STAND with auto=True
  - gateway integration:
      * full gateway path: WELCOME → client HIT → ACTION_ACK + STATE_UPDATE
      * server-only intent from client REJECTED at gateway (never reaches engine)
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game_engine.turn_engine import TurnEngine  # noqa: E402
from game_engine.types import GameState, PlayerState  # noqa: E402
from realtime_v2 import (  # noqa: E402
    EngineBridge,
    Gatekeeper,
    PubSub,
    WebSocketGateway,
)

# Reuse FakeWebSocket + helpers from the gateway tests.
from tests.test_realtime_phase6 import (  # noqa: E402
    FakeWebSocket,
    fake_authenticate,
    VALID_TOKENS,  # noqa: F401
)


# =====================================================================
# Engine fixture: 2 players, hand started, in DRAW phase, alice's turn.
# =====================================================================

def _make_state(table_id: str = "t1") -> GameState:
    state = GameState(table_id=table_id)
    state.players = [
        PlayerState(seat_index=0, user_id="alice", username="Alice", balance_at_start=1000),
        PlayerState(seat_index=1, user_id="bob", username="Bob", balance_at_start=1000),
    ]
    return state


async def _start_hand(engine: TurnEngine) -> None:
    """Drive the engine into DRAW phase via START_HAND + auto-CHECKs."""
    await engine.submit({
        "type": "START_HAND",
        "source": "SERVER",
        "hand_id": "h1",
        "nonce": 0,
        "server_seed": "0" * 64,
        "server_seed_hash": "h" * 64,
        "client_seeds": "",
        "target_score": 30,
    })
    # Wait until BETTING_R1 is set up.
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.005)
        if engine.state.phase == "BETTING_R1":
            break
    # CHECK every player through BETTING_R1 → DRAW
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.005)
        if engine.state.phase == "DRAW":
            return
        if engine.state.phase == "BETTING_R1" and engine.state.current_turn_seat is not None:
            seat = engine.state.current_turn_seat
            user = engine.state.players[seat].user_id
            await engine.submit({
                "type": "CHECK", "user_id": user, "source": "CLIENT",
                "state_version": engine.state.version,
            })
    raise AssertionError(f"engine did not reach DRAW: phase={engine.state.phase}")


@pytest.fixture
async def bridge_with_engine():
    pubsub = PubSub()
    bridge = EngineBridge(pubsub, ack_timeout=2.0)
    state = _make_state("t1")
    engine = TurnEngine(state, turn_timeout_ms=15000)
    bridge.register_engine("t1", engine)
    await engine.start()
    await _start_hand(engine)
    yield bridge, engine, pubsub
    await bridge.unregister_engine("t1")


# =====================================================================
# Bridge: return-value semantics
# =====================================================================

class TestBridgeContract:

    async def test_unknown_table_returns_table_not_found(self):
        bridge = EngineBridge(PubSub())
        result = await bridge.handle_action(
            "ghost-table", "alice", "HIT", {}, 0,
        )
        assert result == {"accepted": False, "error": "TABLE_NOT_FOUND"}

    async def test_get_state_version_unknown_returns_none(self):
        bridge = EngineBridge(PubSub())
        assert await bridge.get_state_version("ghost") is None

    async def test_valid_client_action_accepted(self, bridge_with_engine):
        bridge, engine, _ = bridge_with_engine
        sv = engine.state.version
        # alice is at seat 0 and the current turn
        assert engine.state.current_turn_seat == 0
        result = await bridge.handle_action("t1", "alice", "STAND", {}, sv)
        assert result["accepted"] is True
        assert result["state_version"] == sv + 1

    async def test_stale_state_version_rejected(self, bridge_with_engine):
        bridge, engine, pubsub = bridge_with_engine
        sub = await pubsub.subscribe("table:t1")
        # Pass a stale version.
        result = await bridge.handle_action("t1", "alice", "STAND", {}, 0)
        assert result["accepted"] is False
        assert "OUT_OF_SYNC" in str(result["error"])
        # No broadcast should have been published for a rejected action.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.2)

    async def test_wrong_player_rejected(self, bridge_with_engine):
        bridge, engine, pubsub = bridge_with_engine
        sub = await pubsub.subscribe("table:t1")
        sv = engine.state.version
        # bob acts when it's alice's turn.
        result = await bridge.handle_action("t1", "bob", "STAND", {}, sv)
        assert result["accepted"] is False
        assert "NOT_YOUR_TURN" in str(result["error"])
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.2)


# =====================================================================
# Broadcast envelope shape
# =====================================================================

class TestBroadcastEnvelope:

    async def test_single_action_publishes_one_state_update(self, bridge_with_engine):
        bridge, engine, pubsub = bridge_with_engine
        sub = await pubsub.subscribe("table:t1")
        sv = engine.state.version
        await bridge.handle_action("t1", "alice", "STAND", {}, sv)
        msg = await asyncio.wait_for(sub.get(), timeout=1.0)
        assert msg["type"] == "STATE_UPDATE"
        assert msg["table_id"] == "t1"
        assert msg["state_version"] == sv + 1
        # 2 players + STAND_THRESHOLD[2]=1 -> showdown immediately after first STAND
        assert msg["phase"] in ("DRAW", "PAYOUT", "SHOWDOWN")
        assert "players" in msg and len(msg["players"]) == 2
        assert "events" in msg and len(msg["events"]) >= 1
        assert "pot" in msg
        # No more updates queued for this single action.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.2)

    async def test_broadcast_does_not_leak_cards(self, bridge_with_engine):
        bridge, engine, pubsub = bridge_with_engine
        sub = await pubsub.subscribe("table:t1")
        sv = engine.state.version
        await bridge.handle_action("t1", "alice", "STAND", {}, sv)
        msg = await asyncio.wait_for(sub.get(), timeout=1.0)
        for p in msg["players"]:
            assert "cards" not in p, "broadcast must NOT include face-up cards"
            assert "card_count" in p, "broadcast must include card_count"
            assert isinstance(p["card_count"], int)


# =====================================================================
# Multi-subscriber fan-out
# =====================================================================

class TestMultiSubscriber:

    async def test_two_subscribers_same_update(self, bridge_with_engine):
        bridge, engine, pubsub = bridge_with_engine
        sub_a = await pubsub.subscribe("table:t1")
        sub_b = await pubsub.subscribe("table:t1")
        sv = engine.state.version
        await bridge.handle_action("t1", "alice", "STAND", {}, sv)
        m_a = await asyncio.wait_for(sub_a.get(), timeout=1.0)
        m_b = await asyncio.wait_for(sub_b.get(), timeout=1.0)
        assert m_a == m_b
        assert m_a["state_version"] == sv + 1


# =====================================================================
# State-version monotonic propagation
# =====================================================================

class TestStateVersionPropagation:

    async def test_two_sequential_actions_increment_version(self, bridge_with_engine):
        """With 2 players + threshold=1, alice's STAND triggers showdown
        (single action). To exercise sequential DRAW actions in this test
        we use HIT first (which doesn't end the round)."""
        bridge, engine, pubsub = bridge_with_engine
        sub = await pubsub.subscribe("table:t1")
        sv0 = engine.state.version

        # Action 1: alice HITs (stays alice's turn unless busted; deterministic
        # depending on shuffle, so we tolerate bust transition).
        r1 = await bridge.handle_action("t1", "alice", "HIT", {}, sv0)
        if r1.get("accepted"):
            assert r1["state_version"] == sv0 + 1
            m1 = await asyncio.wait_for(sub.get(), timeout=1.0)
            assert m1["state_version"] == sv0 + 1

            sv1 = engine.state.version
            # Whoever is on turn now (alice if not busted; bob otherwise) — STAND
            seat = engine.state.current_turn_seat
            if seat is not None:
                user = engine.state.players[seat].user_id
                r2 = await bridge.handle_action("t1", user, "STAND", {}, sv1)
                assert r2["accepted"] is True
                assert r2["state_version"] == sv1 + 1
                m2 = await asyncio.wait_for(sub.get(), timeout=1.0)
                assert m2["state_version"] == sv1 + 1
                assert m2["state_version"] > m1["state_version"]
        else:
            # The HIT was rejected (e.g. deck-empty edge); skip the test.
            pytest.skip(f"engine rejected HIT: {r1}")


# =====================================================================
# Timer-fired AUTO_STAND_TIMEOUT triggers broadcast
# =====================================================================

class TestTimeoutBroadcast:

    async def test_auto_stand_timeout_publishes_state_update(self):
        """Use a short turn_timeout so the timer fires during the test.
        Engine must publish a STATE_UPDATE whose events include an
        auto-STAND with reason TURN_TIMEOUT_15S.
        """
        pubsub = PubSub()
        bridge = EngineBridge(pubsub, ack_timeout=2.0)
        state = _make_state("t1")
        # 80 ms timeout so the timer trips quickly.
        engine = TurnEngine(state, turn_timeout_ms=80, grace_ms=20)
        bridge.register_engine("t1", engine)
        await engine.start()

        sub = await pubsub.subscribe("table:t1")
        try:
            await _start_hand(engine)
            # Drain all queued broadcasts. The timer (80ms) may fire either
            # during this drain or just after, so we collect everything and
            # verify a timeout-driven STATE_UPDATE is present.
            messages = []
            try:
                while True:
                    msg = await asyncio.wait_for(sub.get(), timeout=0.3)
                    messages.append(msg)
            except asyncio.TimeoutError:
                pass

            # If the timer hasn't fired yet, wait a bit more.
            if engine.timeout_fires == 0:
                try:
                    msg = await asyncio.wait_for(sub.get(), timeout=2.0)
                    messages.append(msg)
                except asyncio.TimeoutError:
                    pass

            # At least one STATE_UPDATE must contain an AUTO_STAND event.
            timeout_msg = next(
                (m for m in messages
                 if m["type"] == "STATE_UPDATE"
                 and any(e.get("type") == "STAND" and e.get("auto") is True for e in m.get("events", []))),
                None,
            )
            assert timeout_msg is not None, (
                f"no AUTO_STAND broadcast in {[m.get('type') for m in messages]}, "
                f"engine.timeout_fires={engine.timeout_fires}"
            )
            stand_events = [e for e in timeout_msg["events"] if e.get("type") == "STAND" and e.get("auto")]
            assert "TIMEOUT" in stand_events[0].get("reason", "")
            assert engine.timeout_fires >= 1
        finally:
            await bridge.unregister_engine("t1")


# =====================================================================
# Gateway end-to-end: client WS → bridge → engine → client WS broadcast
# =====================================================================

async def _start_gateway_session(
    *, gateway, ws, token="tok-alice", table_id="t1", ip="1.1.1.1",
):
    return asyncio.create_task(
        gateway.handle(ws, token=token, table_id=table_id, ip=ip),
    )


class TestGatewayE2E:

    async def test_gateway_action_round_trip_publishes_to_socket(
        self, bridge_with_engine,
    ):
        bridge, engine, pubsub = bridge_with_engine
        gateway = WebSocketGateway(
            gatekeeper=Gatekeeper(max_per_user=2, max_per_ip=8),
            pubsub=pubsub,
            authenticate=fake_authenticate,
            get_state_version=bridge.get_state_version,
            handle_action=bridge.handle_action,
            ping_interval=10.0,
            ping_timeout=10.0,
        )
        ws = FakeWebSocket()
        task = await _start_gateway_session(gateway=gateway, ws=ws)
        try:
            welcome = await ws.client_recv()
            assert welcome["type"] == "WELCOME"
            sv = welcome["state_version"]
            assert sv == engine.state.version
            # Drain catch-up snapshot messages (post-WELCOME)
            async def _drain_until(predicate, max_msgs=8):
                seen = []
                for _ in range(max_msgs):
                    try:
                        m = await ws.client_recv(timeout=0.3)
                    except asyncio.TimeoutError:
                        break
                    seen.append(m)
                    if predicate(m):
                        return seen
                return seen
            await _drain_until(lambda _: False, max_msgs=2)

            await ws.client_send({
                "type": "STAND", "state_version": sv, "payload": {},
            })

            # Collect post-action messages
            collected = []
            for _ in range(6):
                try:
                    collected.append(await ws.client_recv(timeout=1.0))
                except asyncio.TimeoutError:
                    break
            ack = next((m for m in collected if m["type"] == "ACTION_ACK"), None)
            updates = [m for m in collected if m["type"] == "STATE_UPDATE"]
            assert ack is not None, f"no ACTION_ACK in {[m['type'] for m in collected]}"
            assert ack["action"] == "STAND"
            assert ack["result"]["accepted"] is True
            assert ack["result"]["state_version"] == sv + 1
            assert any(u["state_version"] == sv + 1 for u in updates), \
                f"no STATE_UPDATE at sv+1 in {[u['state_version'] for u in updates]}"
        finally:
            await ws.client_disconnect()
            await asyncio.wait_for(task, timeout=2)

    async def test_gateway_blocks_server_only_action_from_client(
        self, bridge_with_engine,
    ):
        """AUTO_STAND_TIMEOUT must not cross the gateway from client side,
        and consequently must NOT reach the engine."""
        bridge, engine, pubsub = bridge_with_engine
        gateway = WebSocketGateway(
            gatekeeper=Gatekeeper(max_per_user=2, max_per_ip=8),
            pubsub=pubsub,
            authenticate=fake_authenticate,
            get_state_version=bridge.get_state_version,
            handle_action=bridge.handle_action,
            ping_interval=10.0,
            ping_timeout=10.0,
        )
        sub = await pubsub.subscribe("table:t1")
        ws = FakeWebSocket()
        task = await _start_gateway_session(gateway=gateway, ws=ws)
        try:
            await ws.client_recv()  # WELCOME
            # Drain snapshot messages
            for _ in range(3):
                try:
                    await ws.client_recv(timeout=0.2)
                except asyncio.TimeoutError:
                    break
            sv_before = engine.state.version
            await ws.client_send({
                "type": "AUTO_STAND_TIMEOUT", "state_version": sv_before, "payload": {},
            })
            # Gateway treats "AUTO_STAND_TIMEOUT" as an UNKNOWN_TYPE since
            # it's not in CLIENT_ACTIONS. The connection stays open, no
            # broadcast is produced, and engine state is unchanged.
            # Find the ERROR message (may follow snapshot messages).
            err = None
            for _ in range(4):
                try:
                    m = await ws.client_recv(timeout=0.5)
                    if m["type"] == "ERROR":
                        err = m
                        break
                except asyncio.TimeoutError:
                    break
            assert err is not None
            assert err["code"] == "UNKNOWN_TYPE"
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(sub.get(), timeout=0.2)
            assert engine.state.version == sv_before
        finally:
            await ws.client_disconnect()
            await asyncio.wait_for(task, timeout=2)

    async def test_gateway_two_clients_both_receive_state_update(
        self, bridge_with_engine,
    ):
        bridge, engine, pubsub = bridge_with_engine
        gateway = WebSocketGateway(
            gatekeeper=Gatekeeper(max_per_user=2, max_per_ip=8),
            pubsub=pubsub,
            authenticate=fake_authenticate,
            get_state_version=bridge.get_state_version,
            handle_action=bridge.handle_action,
            ping_interval=10.0,
            ping_timeout=10.0,
        )
        ws_a, ws_b = FakeWebSocket(), FakeWebSocket()
        ta = await _start_gateway_session(
            gateway=gateway, ws=ws_a, token="tok-alice", ip="1.1.1.1",
        )
        tb = await _start_gateway_session(
            gateway=gateway, ws=ws_b, token="tok-bob", ip="2.2.2.2",
        )
        try:
            await ws_a.client_recv()  # WELCOME
            await ws_b.client_recv()  # WELCOME
            # Drain snapshot messages on each socket
            for ws in (ws_a, ws_b):
                for _ in range(3):
                    try:
                        await ws.client_recv(timeout=0.2)
                    except asyncio.TimeoutError:
                        break
            sv = engine.state.version

            await ws_a.client_send({
                "type": "STAND", "state_version": sv, "payload": {},
            })

            # Each socket must see one STATE_UPDATE with version sv+1.
            async def collect_state_update(ws):
                for _ in range(6):
                    msg = await ws.client_recv(timeout=1.0)
                    if msg["type"] == "STATE_UPDATE" and msg["state_version"] == sv + 1:
                        return msg
                raise AssertionError("no STATE_UPDATE received")

            ma = await collect_state_update(ws_a)
            mb = await collect_state_update(ws_b)
            assert ma["state_version"] == sv + 1
            assert mb["state_version"] == sv + 1
            assert ma == mb
        finally:
            await ws_a.client_disconnect()
            await ws_b.client_disconnect()
            await asyncio.wait_for(ta, timeout=2)
            await asyncio.wait_for(tb, timeout=2)
