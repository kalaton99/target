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
        "target_score": 30,
    })
    deadline = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.005)
        if engine.state.phase == "BETTING_R1":
            break
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

        # START_HAND -> CHECK through betting -> DEAL_INITIAL -> DRAW
        await _start_hand(engine)

        # Drain all queued messages on each sub.
        async def _drain(sub):
            out = []
            try:
                while True:
                    out.append(await asyncio.wait_for(sub.get(), timeout=0.3))
            except asyncio.TimeoutError:
                pass
            return out
        public_msgs = await _drain(public_sub)
        alice_msgs = await _drain(alice_sub)
        bob_msgs = await _drain(bob_sub)

        # Public must have STATE_UPDATEs, never carry face-up cards.
        assert any(m["type"] == "STATE_UPDATE" for m in public_msgs)
        for m in public_msgs:
            for p in m.get("players", []):
                assert "cards" not in p, "public STATE_UPDATE must not leak cards"

        # Each player sub: every message must be PRIVATE_STATE for its own user.
        for m in alice_msgs:
            assert m["type"] == "PRIVATE_STATE"
            assert m["user_id"] == "alice"
        for m in bob_msgs:
            assert m["type"] == "PRIVATE_STATE"
            assert m["user_id"] == "bob"

        # The post-deal PRIVATE_STATE has the player's actual card.
        last_alice = alice_msgs[-1]
        last_bob = bob_msgs[-1]
        assert last_alice["seat"] == 0
        assert last_bob["seat"] == 1
        # Initial deal is 1 card per player (TARGET v2)
        assert len(last_alice["cards"]) >= 1
        assert len(last_bob["cards"]) >= 1
        # Cards must differ (deck-popped sequentially).
        assert last_alice["cards"] != last_bob["cards"]

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
        # Drain everything that arrived on alice's topic.
        msgs = []
        try:
            while True:
                msgs.append(await asyncio.wait_for(alice_sub.get(), timeout=0.3))
        except asyncio.TimeoutError:
            pass
        assert msgs, "expected at least one PRIVATE_STATE on alice topic"
        # Every single message must belong to alice.
        for m in msgs:
            assert m["type"] == "PRIVATE_STATE"
            assert m["user_id"] == "alice"

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

            # Drain everything each socket received and find the latest
            # STATE_UPDATE + PRIVATE_STATE in DRAW phase (post-deal).
            async def drain(ws):
                got = []
                for _ in range(20):
                    try:
                        got.append(await ws.client_recv(timeout=0.3))
                    except asyncio.TimeoutError:
                        break
                return got

            msgs_a = await drain(ws_a)
            msgs_b = await drain(ws_b)

            # Pick the most recent PRIVATE_STATE that has cards (post-deal).
            priv_a = next(
                (m for m in reversed(msgs_a) if m["type"] == "PRIVATE_STATE" and m.get("cards")),
                None,
            )
            priv_b = next(
                (m for m in reversed(msgs_b) if m["type"] == "PRIVATE_STATE" and m.get("cards")),
                None,
            )
            assert priv_a is not None, f"no PRIVATE_STATE w/ cards on alice: {[m['type'] for m in msgs_a]}"
            assert priv_b is not None, f"no PRIVATE_STATE w/ cards on bob:   {[m['type'] for m in msgs_b]}"
            assert priv_a["user_id"] == "alice"
            assert priv_b["user_id"] == "bob"
            assert priv_a["cards"] != priv_b["cards"]

            # Pick a matching pair of public STATE_UPDATEs (same state_version).
            pubs_a = [m for m in msgs_a if m["type"] == "STATE_UPDATE"]
            pubs_b = [m for m in msgs_b if m["type"] == "STATE_UPDATE"]
            assert pubs_a and pubs_b
            common = {m["state_version"] for m in pubs_a} & {m["state_version"] for m in pubs_b}
            assert common, "no common state_version between sockets"
            sv = max(common)
            pub_a = next(m for m in pubs_a if m["state_version"] == sv)
            pub_b = next(m for m in pubs_b if m["state_version"] == sv)
            assert pub_a == pub_b
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
