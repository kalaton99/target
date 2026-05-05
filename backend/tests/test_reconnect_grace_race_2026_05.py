"""2026-05 v3 — Reconnect-grace race regression tests.

Pin the contract that a grace-expiry timer can NEVER yank a player
who has reconnected during the grace window — even if the reconnect
notify hits an asyncio gap before the disconnect notify finishes
scheduling the timer.

Before the fix:
  1. WS-A closes → gateway calls `notify_disconnect`.
  2. `notify_disconnect` pops the prior grace task (None), sets
     `connected=False`, then `await _publish_state(...)`.
  3. Concurrently WS-B opens → gateway calls `notify_connect`.
     During step 2's await, `notify_connect` pops the grace_tasks
     entry (still None — the new task hasn't been scheduled yet),
     sets `connected=True`, publishes PRESENCE.
  4. `notify_disconnect` resumes after its await, calls
     `loop.create_task(_grace_expiry)` — ORPHAN task.
  5. `_grace_expiry` sleeps `grace_seconds`, then sets
     `player.sitting_out=True` even though the player is currently
     connected.

After the fix:
  - `_grace_expiry` re-resolves the player after the sleep and
    checks `player.connected`. If True (reconnected during grace),
    the expiry is a no-op.
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
from realtime_v2.bridge import EngineBridge  # noqa: E402
from realtime_v2.pubsub import PubSub  # noqa: E402


def _make_engine_with_two_seated_players():
    """4-seat (target=30) table with 2 humans seated — the minimum
    legal start for the 4-seat tier per GAME_RULES_LOCKED.md §2.
    There is no 2-seat table type."""
    state = GameState(table_id="grace_t", target_score=30, stake=100)
    state.players = [
        PlayerState(seat_index=0, user_id="u_a", username="A",
                    balance_at_start=10000),
        PlayerState(seat_index=1, user_id="u_b", username="B",
                    balance_at_start=10000),
    ]
    return TurnEngine(state)


def _make_bridge_with_short_grace(grace=0.2):
    """Use a tiny grace window so test runs in <1s. The clamp in the
    bridge enforces [GRACE_MIN, GRACE_MAX] but we monkey-patch
    `_grace_seconds` after construction to bypass it for the test."""
    pubsub = PubSub()
    bridge = EngineBridge(pubsub, ack_timeout=1.0)
    bridge._grace_seconds = grace
    return bridge


@pytest.mark.asyncio
async def test_reconnect_during_grace_does_not_set_sitting_out():
    """The simplest expression of the contract: notify_disconnect →
    (within the grace window) notify_connect → grace expires →
    player must remain `sitting_out=False`.
    """
    bridge = _make_bridge_with_short_grace(grace=0.2)
    engine = _make_engine_with_two_seated_players()
    bridge.register_engine("grace_t", engine)
    try:
        # Player A disconnects.
        await bridge.notify_disconnect("grace_t", "u_a")
        assert engine.state.players[0].connected is False

        # ... mid-grace, A reconnects.
        await asyncio.sleep(0.05)
        await bridge.notify_connect("grace_t", "u_a")
        assert engine.state.players[0].connected is True

        # Wait past the grace window.
        await asyncio.sleep(0.4)

        # The grace expiry MUST NOT have flipped sitting_out.
        assert engine.state.players[0].sitting_out is False, (
            "reconnected player was incorrectly yanked to sitting_out "
            "by a stale grace timer"
        )
        assert engine.state.players[0].connected is True
    finally:
        await bridge.unregister_engine("grace_t")


@pytest.mark.asyncio
async def test_orphan_grace_task_after_concurrent_reconnect_is_a_no_op():
    """Force the race directly: schedule a grace expiry, then mark the
    player connected before the sleep completes. The expiry must
    detect the reconnect and exit cleanly without mutating state.

    This reproduces the orphan-task scenario where notify_disconnect's
    `create_task(_grace_expiry)` lands AFTER notify_connect has
    already cancelled the previous (None) entry and flipped
    connected=True. Without the `player.connected` check inside
    `_grace_expiry`, the orphan task would complete its sleep and
    mark the connected player sitting_out.
    """
    bridge = _make_bridge_with_short_grace(grace=0.15)
    engine = _make_engine_with_two_seated_players()
    bridge.register_engine("grace_t", engine)
    try:
        # Disconnect player A but DO NOT wait for the timer to expire.
        await bridge.notify_disconnect("grace_t", "u_a")
        assert engine.state.players[0].connected is False

        # Forcibly mark connected=True (simulating a reconnect that
        # raced inside the disconnect's publish_state await), but
        # WITHOUT cancelling the bridge's grace task — that's the
        # exact orphan scenario.
        engine.state.players[0].connected = True
        # We deliberately leave bridge._grace_tasks intact so the
        # task is still scheduled. The test verifies the expiry
        # function self-cancels based on `player.connected`.

        # Wait past the grace window.
        await asyncio.sleep(0.3)

        assert engine.state.players[0].sitting_out is False, (
            "orphan grace timer fired against a connected player"
        )
    finally:
        await bridge.unregister_engine("grace_t")


@pytest.mark.asyncio
async def test_grace_still_fires_when_user_truly_disconnects():
    """Inverse of the above — when the user does NOT reconnect, the
    grace timer must still mark them `sitting_out=True`. We must not
    have weakened the original contract.
    """
    bridge = _make_bridge_with_short_grace(grace=0.15)
    engine = _make_engine_with_two_seated_players()
    bridge.register_engine("grace_t", engine)
    try:
        await bridge.notify_disconnect("grace_t", "u_a")
        assert engine.state.players[0].connected is False

        # Wait past the grace window — no reconnect happens.
        await asyncio.sleep(0.4)

        assert engine.state.players[0].sitting_out is True, (
            "grace timer failed to mark a truly-disconnected player "
            "as sitting_out (original contract regression)"
        )
        assert engine.state.players[0].connected is False
    finally:
        await bridge.unregister_engine("grace_t")
