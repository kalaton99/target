"""Phase 6 (extension) — Per-viewer PRIVATE_STATE tests.

Verifies:
  - bridge publishes one PRIVATE_STATE per player on their per-user topic
  - PRIVATE_STATE contains the player's actual face-up cards
  - PRIVATE_STATE for player X is NEVER published on the public table topic
  - PRIVATE_STATE for player X is NOT published on player Y's user topic
  - public STATE_UPDATE never includes face-up cards
  - through the gateway, each connected client receives only their own
    PRIVATE_STATE (and the shared public STATE_UPDATE)
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
from tests.test_realtime_phase6 import FakeWebSocket, fake_authenticate  # noqa: E402


def _make_state(table_id: str = "t1") -> GameState:
    state = GameState(table_id=table_id)
    state.players = [
        PlayerState(seat_index=0, user_id="alice", username="Alice", balance_at_start=1000),
        PlayerState(seat_index=1, user_id="bob", username="Bob", balance_at_start=1000),
    ]
    return state


async def _start_hand(engine: TurnEngine) -> None:
    await engine.submit({
        "type": "START_HAND",
        "source": "SERVER",
        "hand_id": "h1",
        "nonce": 0,
        "server_seed": "0" * 64,
        "server_seed_hash": "h" * 64,
        "client_seeds": "",
    })
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.005)
        if engine.state.phase == "DRAW":
            return
    raise AssertionError("engine did not reach DRAW")


@pytest.fixture
async def bridge_with_engine():
    pubsub = PubSub()
    bridge = EngineBridge(pubsub, ack_timeout=2.0)
    state = _make_state("t1")
    engine = TurnEngine(state, turn_timeout_ms=15000)
    bridge.register_engine("t1", engine)
    await engine.start()
    yield bridge, engine, pubsub
    await bridge.unregister_engine("t1")


# =====================================================================
# Pubsub-level: private topic semantics
# =====================================================================

class TestPrivateStatePubSub:

    async def test_each_player_receives_own_private_state(self, bridge_with_engine):
        _, engine, pubsub = bridge_with_engine
        public_sub = await pubsub.subscribe("table:t1")
        alice_sub = await pubsub.subscribe("table:t1:user:alice")
        bob_sub = await pubsub.subscribe("table:t1:user:bob")

        # START_HAND — server-driven; engine deals cards.
        await _start_hand(engine)

        # The public sub gets one STATE_UPDATE (no cards).
        public_msg = await asyncio.wait_for(public_sub.get(), timeout=1.0)
        assert public_msg["type"] == "STATE_UPDATE"
        for p in public_msg["players"]:
            assert "cards" not in p, "public STATE_UPDATE must not leak cards"

        # Each player sub gets exactly one PRIVATE_STATE with their cards.
        m_alice = await asyncio.wait_for(alice_sub.get(), timeout=1.0)
        m_bob = await asyncio.wait_for(bob_sub.get(), timeout=1.0)
        assert m_alice["type"] == "PRIVATE_STATE"
        assert m_alice["user_id"] == "alice"
        assert m_alice["seat"] == 0
        assert isinstance(m_alice["cards"], list) and len(m_alice["cards"]) == 2
        assert m_bob["type"] == "PRIVATE_STATE"
        assert m_bob["user_id"] == "bob"
        assert m_bob["seat"] == 1
        assert isinstance(m_bob["cards"], list) and len(m_bob["cards"]) == 2

        # Cards must be DIFFERENT (deck-popped sequentially).
        assert m_alice["cards"] != m_bob["cards"]

        # No more messages on either private topic after one event.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(alice_sub.get(), timeout=0.15)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(bob_sub.get(), timeout=0.15)

    async def test_private_state_not_published_on_public_topic(self, bridge_with_engine):
        _, engine, pubsub = bridge_with_engine
        public_sub = await pubsub.subscribe("table:t1")
        await _start_hand(engine)
        # Drain everything that arrived on public.
        seen_types = set()
        try:
            while True:
                msg = await asyncio.wait_for(public_sub.get(), timeout=0.2)
                seen_types.add(msg["type"])
        except asyncio.TimeoutError:
            pass
        assert "STATE_UPDATE" in seen_types
        assert "PRIVATE_STATE" not in seen_types

    async def test_alice_topic_does_not_carry_bob_private(self, bridge_with_engine):
        _, engine, pubsub = bridge_with_engine
        alice_sub = await pubsub.subscribe("table:t1:user:alice")
        await _start_hand(engine)
        msg = await asyncio.wait_for(alice_sub.get(), timeout=1.0)
        assert msg["user_id"] == "alice"
        # No additional message should arrive (would be bob's private).
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(alice_sub.get(), timeout=0.2)

    async def test_subsequent_action_publishes_fresh_private_state(self, bridge_with_engine):
        bridge, engine, pubsub = bridge_with_engine
        alice_sub = await pubsub.subscribe("table:t1:user:alice")
        await _start_hand(engine)
        first = await asyncio.wait_for(alice_sub.get(), timeout=1.0)
        first_sv = first["state_version"]
        first_cards = list(first["cards"])

        # Alice HITs — should result in a fresh PRIVATE_STATE for alice.
        sv = engine.state.version
        result = await bridge.handle_action("t1", "alice", "HIT", {}, sv)
        assert result["accepted"] is True

        second = await asyncio.wait_for(alice_sub.get(), timeout=1.0)
        assert second["type"] == "PRIVATE_STATE"
        assert second["state_version"] > first_sv
        # New card appended.
        assert len(second["cards"]) >= len(first_cards)


# =====================================================================
# Gateway-level: each connected client sees only own cards
# =====================================================================

async def _start_session(*, gateway, ws, token, ip):
    return asyncio.create_task(
        gateway.handle(ws, token=token, table_id="t1", ip=ip),
    )


class TestPrivateStateOverGateway:

    async def test_two_clients_each_see_only_own_cards(self, bridge_with_engine):
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
        ta = await _start_session(gateway=gateway, ws=ws_a, token="tok-alice", ip="1.1.1.1")
        tb = await _start_session(gateway=gateway, ws=ws_b, token="tok-bob", ip="2.2.2.2")
        try:
            await ws_a.client_recv()  # WELCOME
            await ws_b.client_recv()  # WELCOME

            # Server starts the hand directly via engine.
            await _start_hand(engine)

            # Collect at most 4 messages per socket (STATE_UPDATE + PRIVATE_STATE
            # = exactly 2 per socket per event).
            async def collect(ws, n=2):
                got = []
                for _ in range(n):
                    got.append(await ws.client_recv(timeout=1.0))
                return got

            msgs_a = await collect(ws_a, n=2)
            msgs_b = await collect(ws_b, n=2)
            types_a = sorted(m["type"] for m in msgs_a)
            types_b = sorted(m["type"] for m in msgs_b)
            assert types_a == ["PRIVATE_STATE", "STATE_UPDATE"]
            assert types_b == ["PRIVATE_STATE", "STATE_UPDATE"]

            priv_a = next(m for m in msgs_a if m["type"] == "PRIVATE_STATE")
            priv_b = next(m for m in msgs_b if m["type"] == "PRIVATE_STATE")
            pub_a = next(m for m in msgs_a if m["type"] == "STATE_UPDATE")
            pub_b = next(m for m in msgs_b if m["type"] == "STATE_UPDATE")

            # Each player sees only their own user_id in PRIVATE_STATE.
            assert priv_a["user_id"] == "alice"
            assert priv_b["user_id"] == "bob"
            # Cards differ.
            assert priv_a["cards"] != priv_b["cards"]
            # Public is identical for both clients.
            assert pub_a == pub_b
            # Public never leaks cards.
            for p in pub_a["players"]:
                assert "cards" not in p
                assert isinstance(p["card_count"], int)
        finally:
            await ws_a.client_disconnect()
            await ws_b.client_disconnect()
            await asyncio.wait_for(ta, timeout=2)
            await asyncio.wait_for(tb, timeout=2)

    async def test_disconnect_releases_both_topics(self, bridge_with_engine):
        bridge, _engine, pubsub = bridge_with_engine
        gateway = WebSocketGateway(
            gatekeeper=Gatekeeper(),
            pubsub=pubsub,
            authenticate=fake_authenticate,
            get_state_version=bridge.get_state_version,
            handle_action=bridge.handle_action,
            ping_interval=10.0,
            ping_timeout=10.0,
        )
        ws = FakeWebSocket()
        task = await _start_session(gateway=gateway, ws=ws, token="tok-alice", ip="1.1.1.1")
        await ws.client_recv()  # WELCOME
        assert pubsub.subscriber_count("table:t1") == 1
        assert pubsub.subscriber_count("table:t1:user:alice") == 1
        await ws.client_disconnect()
        await asyncio.wait_for(task, timeout=2)
        assert pubsub.subscriber_count("table:t1") == 0
        assert pubsub.subscriber_count("table:t1:user:alice") == 0
