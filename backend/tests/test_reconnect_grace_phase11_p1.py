"""Phase 11 P1 — reconnect-grace timer tests.

Coverage:
  - bridge.notify_disconnect → player.connected becomes False
  - bridge.notify_disconnect → grace task scheduled
  - bridge.notify_connect inside grace → task cancelled, sitting_out untouched
  - grace expiry → player.sitting_out becomes True
  - grace clamped to [GRACE_MIN, GRACE_MAX]
  - disconnected current-turn seat still AUTO_STAND_TIMEOUTs at the
    engine's normal 15s budget (existing turn timer is unaffected by
    presence)
  - unregister_engine cancels in-flight grace tasks
  - notify_* on unknown table/user is a safe no-op
  - presence events are broadcast to subscribers as STATE_UPDATE.events

Engine state is not retroactively rewritten: hand_actions / state.version
movements are driven exclusively by `engine.submit(...)`, never by the
presence layer.
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
from realtime_v2 import EngineBridge, PubSub  # noqa: E402

# Reuse helpers from the existing bridge tests.
from tests.test_realtime_phase6_bridge import _start_hand  # noqa: E402


def _make_state(table_id: str = "t1") -> GameState:
    state = GameState(table_id=table_id)
    state.players = [
        PlayerState(seat_index=0, user_id="alice", username="Alice", balance_at_start=1000),
        PlayerState(seat_index=1, user_id="bob", username="Bob", balance_at_start=1000),
    ]
    return state


@pytest.fixture
async def bridge_short_grace():
    """EngineBridge with a tight grace window for fast tests.

    The bridge clamps grace_seconds to [20, 30] in production. We bypass
    that floor here by patching the instance attribute after construction
    so the suite stays under a few hundred ms per case.
    """
    pubsub = PubSub()
    bridge = EngineBridge(pubsub, ack_timeout=2.0)
    bridge._grace_seconds = 0.1  # noqa: SLF001 — test-only override
    state = _make_state("t1")
    engine = TurnEngine(state, turn_timeout_ms=15000)
    bridge.register_engine("t1", engine)
    await engine.start()
    yield bridge, engine, pubsub
    await bridge.unregister_engine("t1")


# =====================================================================
# Grace-window clamp
# =====================================================================

class TestGraceClamp:

    def test_grace_default_is_25(self):
        b = EngineBridge(PubSub())
        assert b.grace_seconds == 25.0

    def test_grace_clamped_low(self):
        b = EngineBridge(PubSub(), grace_seconds=5.0)
        assert b.grace_seconds == EngineBridge.GRACE_MIN  # 20

    def test_grace_clamped_high(self):
        b = EngineBridge(PubSub(), grace_seconds=600.0)
        assert b.grace_seconds == EngineBridge.GRACE_MAX  # 30

    def test_grace_in_band_kept(self):
        b = EngineBridge(PubSub(), grace_seconds=22.5)
        assert b.grace_seconds == 22.5


# =====================================================================
# Disconnect / reconnect / expiry mechanics
# =====================================================================

class TestPresenceLifecycle:

    async def test_disconnect_marks_disconnected_and_starts_grace(self, bridge_short_grace):
        bridge, engine, pubsub = bridge_short_grace
        sub = await pubsub.subscribe("table:t1")
        alice = engine.state.players[0]
        assert alice.connected is True

        await bridge.notify_disconnect("t1", "alice")
        assert alice.connected is False
        assert alice.sitting_out is False  # grace not yet expired
        assert ("t1", "alice") in bridge._grace_tasks  # noqa: SLF001

        # Presence STATE_UPDATE goes out with a PRESENCE event.
        msg = await asyncio.wait_for(sub.get(), timeout=0.5)
        assert msg["type"] == "STATE_UPDATE"
        evs = msg["events"]
        assert any(
            e.get("type") == "PRESENCE" and e.get("user_id") == "alice"
            and e.get("connected") is False
            for e in evs
        ), evs

    async def test_reconnect_within_grace_restores_seat(self, bridge_short_grace):
        bridge, engine, pubsub = bridge_short_grace
        sub = await pubsub.subscribe("table:t1")
        alice = engine.state.players[0]

        await bridge.notify_disconnect("t1", "alice")
        await asyncio.wait_for(sub.get(), timeout=0.5)  # consume PRESENCE off

        # Reconnect well within the 0.1s grace window.
        await asyncio.sleep(0.02)
        await bridge.notify_connect("t1", "alice")

        assert alice.connected is True
        assert alice.sitting_out is False
        assert ("t1", "alice") not in bridge._grace_tasks  # noqa: SLF001

        # Presence STATE_UPDATE for the reconnect goes out too.
        msg = await asyncio.wait_for(sub.get(), timeout=0.5)
        evs = msg["events"]
        assert any(
            e.get("type") == "PRESENCE" and e.get("connected") is True
            for e in evs
        ), evs

        # And no further STATE_UPDATEs should fire — the grace task was cancelled.
        await asyncio.sleep(0.2)  # > grace window
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.1)
        assert alice.sitting_out is False

    async def test_grace_expiry_sets_sitting_out(self, bridge_short_grace):
        bridge, engine, pubsub = bridge_short_grace
        sub = await pubsub.subscribe("table:t1")
        alice = engine.state.players[0]

        await bridge.notify_disconnect("t1", "alice")
        await asyncio.wait_for(sub.get(), timeout=0.5)  # PRESENCE off

        # Wait for grace to elapse.
        await asyncio.sleep(0.15)  # > 0.1s grace
        msg = await asyncio.wait_for(sub.get(), timeout=0.5)
        evs = msg["events"]
        assert any(
            e.get("type") == "PRESENCE_GRACE_EXPIRED" and e.get("user_id") == "alice"
            for e in evs
        ), evs
        assert alice.sitting_out is True
        assert alice.connected is False
        assert ("t1", "alice") not in bridge._grace_tasks  # noqa: SLF001

    async def test_reconnect_after_expiry_clears_offline_but_not_sitting_out(self, bridge_short_grace):
        # The user is still sitting_out for the engine's purposes (skipped
        # in future hand starts) but their presence flag should flip back.
        bridge, engine, pubsub = bridge_short_grace
        alice = engine.state.players[0]

        await bridge.notify_disconnect("t1", "alice")
        await asyncio.sleep(0.15)
        assert alice.sitting_out is True
        assert alice.connected is False

        await bridge.notify_connect("t1", "alice")
        assert alice.connected is True
        assert alice.sitting_out is True  # only the engine can flip this back


# =====================================================================
# Engine non-interference
# =====================================================================

class TestEngineNotRetroactivelyChanged:

    async def test_disconnected_active_player_still_auto_stands_on_turn_timeout(self, bridge_short_grace):
        bridge, engine, pubsub = bridge_short_grace
        # Drive the engine into DRAW with alice's turn.
        sub = await pubsub.subscribe("table:t1")
        await _start_hand(engine)
        # Drain any STATE_UPDATEs queued by engine setup.
        while True:
            try:
                await asyncio.wait_for(sub.get(), timeout=0.1)
            except asyncio.TimeoutError:
                break

        assert engine.state.phase == "DRAW_1"
        assert engine.state.current_turn_seat == 0
        sv_before = engine.state.version

        # Alice disconnects mid-turn. Grace timer is now ticking, but
        # the engine's 15s turn timer is NOT touched — so AUTO_STAND_TIMEOUT
        # must still fire when we submit the synthetic timeout intent.
        await bridge.notify_disconnect("t1", "alice")
        # Drain the PRESENCE STATE_UPDATE.
        await asyncio.wait_for(sub.get(), timeout=0.5)

        # Simulate the engine's internal timer firing AUTO_STAND_TIMEOUT
        # for alice. (We submit it directly via engine.submit because we
        # don't want to wait the real 15s wall-clock in tests.)
        await engine.submit({
            "type": "AUTO_STAND_TIMEOUT",
            "user_id": "alice",
            "source": "SERVER",
            "state_version": engine.state.version,
        })
        # Wait for engine to process.
        deadline = asyncio.get_event_loop().time() + 1.0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.005)
            if engine.state.version > sv_before:
                break
        assert engine.state.version > sv_before
        # Alice must be marked stood by AUTO_STAND_TIMEOUT — exactly the
        # same outcome as if she'd been online but silent. The presence
        # layer did not interfere.
        assert engine.state.players[0].stood is True
        # Presence flags untouched by the engine path.
        assert engine.state.players[0].connected is False
        assert engine.state.players[0].sitting_out is False  # grace not yet expired

    async def test_unregister_cancels_inflight_grace_tasks(self, bridge_short_grace):
        bridge, engine, _ = bridge_short_grace
        await bridge.notify_disconnect("t1", "alice")
        assert ("t1", "alice") in bridge._grace_tasks  # noqa: SLF001
        await bridge.unregister_engine("t1")
        assert ("t1", "alice") not in bridge._grace_tasks  # noqa: SLF001


# =====================================================================
# Safe no-ops
# =====================================================================

class TestSafeNoops:

    async def test_notify_disconnect_unknown_table_is_noop(self):
        bridge = EngineBridge(PubSub())
        # Should not raise.
        await bridge.notify_disconnect("ghost", "alice")
        assert bridge._grace_tasks == {}  # noqa: SLF001

    async def test_notify_connect_unknown_user_is_noop(self, bridge_short_grace):
        bridge, _, _ = bridge_short_grace
        # Should not raise even when user isn't seated.
        await bridge.notify_connect("t1", "stranger")

    async def test_double_disconnect_is_idempotent(self, bridge_short_grace):
        bridge, engine, pubsub = bridge_short_grace
        sub = await pubsub.subscribe("table:t1")
        await bridge.notify_disconnect("t1", "alice")
        await asyncio.wait_for(sub.get(), timeout=0.5)
        # Second disconnect refreshes the grace timer (same key replaced).
        await bridge.notify_disconnect("t1", "alice")
        assert engine.state.players[0].connected is False
        # The second call should NOT re-broadcast a duplicate PRESENCE
        # event (player.connected is already False).
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.1)
