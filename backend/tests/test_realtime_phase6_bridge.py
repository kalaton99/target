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
        assert msg["phase"] in ("DRAW", "BETTING")
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
        bridge, engine, pubsub = bridge_with_engine
        sub = await pubsub.subscribe("table:t1")
        sv0 = engine.state.version

        # Action 1: alice STANDS → turn moves to bob (still DRAW)
        r1 = await bridge.handle_action("t1", "alice", "STAND", {}, sv0)
        assert r1["accepted"] is True
        assert r1["state_version"] == sv0 + 1
        m1 = await asyncio.wait_for(sub.get(), timeout=1.0)
        assert m1["state_version"] == sv0 + 1

        # If the engine moved to BETTING (e.g. only 2 players with both
        # standing), bob would be the next actor in BETTING. Either way
        # the next action is "bob STAND" or "bob CHECK" depending on phase.
        # We exercise whichever phase we're in:
        sv1 = engine.state.version
        if engine.state.phase == "DRAW":
            r2 = await bridge.handle_action("t1", "bob", "STAND", {}, sv1)
        else:
            assert engine.state.phase == "BETTING"
            r2 = await bridge.handle_action("t1", "bob", "CHECK", {}, sv1)
        assert r2["accepted"] is True
        assert r2["state_version"] == sv1 + 1
        m2 = await asyncio.wait_for(sub.get(), timeout=1.0)
        assert m2["state_version"] == sv1 + 1
        assert m2["state_version"] > m1["state_version"]


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
            # Drain the START_HAND broadcast.
            start_msg = await asyncio.wait_for(sub.get(), timeout=1.0)
            assert start_msg["type"] == "STATE_UPDATE"
            sv_after_deal = start_msg["state_version"]

            # No client action — timer fires AUTO_STAND_TIMEOUT.
            timeout_msg = await asyncio.wait_for(sub.get(), timeout=2.0)
            assert timeout_msg["type"] == "STATE_UPDATE"
            assert timeout_msg["state_version"] > sv_after_deal
            stand_events = [e for e in timeout_msg["events"] if e.get("type") == "STAND"]
            assert stand_events, f"no STAND event in {timeout_msg['events']}"
            assert stand_events[0]["auto"] is True
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

            await ws.client_send({
                "type": "STAND", "state_version": sv, "payload": {},
            })

            # We expect both an ACTION_ACK and a STATE_UPDATE; order
            # between the two is not contractually fixed, so collect both.
            seen = []
            for _ in range(3):
                try:
                    seen.append(await ws.client_recv(timeout=1.0))
                except asyncio.TimeoutError:
                    break
            types = [m["type"] for m in seen]
            assert "ACTION_ACK" in types
            assert "STATE_UPDATE" in types
            ack = next(m for m in seen if m["type"] == "ACTION_ACK")
            update = next(m for m in seen if m["type"] == "STATE_UPDATE")
            assert ack["action"] == "STAND"
            assert ack["result"]["accepted"] is True
            assert ack["result"]["state_version"] == sv + 1
            assert update["state_version"] == sv + 1
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
            sv_before = engine.state.version
            await ws.client_send({
                "type": "AUTO_STAND_TIMEOUT", "state_version": sv_before, "payload": {},
            })
            # Gateway treats "AUTO_STAND_TIMEOUT" as an UNKNOWN_TYPE since
            # it's not in CLIENT_ACTIONS. The connection stays open, no
            # broadcast is produced, and engine state is unchanged.
            err = await ws.client_recv()
            assert err["type"] == "ERROR"
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
            sv = engine.state.version

            await ws_a.client_send({
                "type": "STAND", "state_version": sv, "payload": {},
            })

            # Each socket must see one STATE_UPDATE with version sv+1.
            async def collect_state_update(ws):
                for _ in range(4):
                    msg = await ws.client_recv(timeout=1.0)
                    if msg["type"] == "STATE_UPDATE":
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
