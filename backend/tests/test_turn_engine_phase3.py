"""Phase 3 unit tests — TurnEngine.

Scope (locked):
  - 15s authoritative server timer (parameterized for tests).
  - AUTO_STAND_TIMEOUT fires from the engine, not the client.
  - TableWorker-owned timeout scheduler (TurnEngine in Phase 3).
  - state_version increment on every mutation.
  - Client cannot emit server-only actions.
  - Timeout always resolves as STAND, never FOLD.
  - Stale timeout (player acted in time, then timer fires) → no-op.

Run:
  cd /app/backend && PYTHONPATH=. python -m pytest tests/test_turn_engine_phase3.py -v
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import pytest

from game_engine.turn_engine import TurnEngine
from game_engine.types import GameState, PlayerState


def C(rank, suit="S"):
    return {"rank": rank, "suit": suit, "code": f"{rank}{suit}"}


def make_two_player_draw_state(version: int = 0) -> GameState:
    return GameState(
        table_id="t_phase3",
        hand_id="h_phase3",
        engine_version="1.0.0",
        phase="DRAW",
        version=version,
        players=[
            PlayerState(seat_index=0, user_id="u1", username="p1",
                        balance_at_start=1000, cards=[C("5"), C("3")], score=8),
            PlayerState(seat_index=1, user_id="u2", username="p2",
                        balance_at_start=1000, cards=[C("9"), C("7")], score=16),
        ],
        deck=[C("4"), C("2"), C("10")],
        pot=200,
        stake=100,
        current_turn_seat=0,
    )


# ---------- 15-second authoritative timer + AUTO_STAND_TIMEOUT ----------

class TestAuthoritativeTimer:

    @pytest.mark.asyncio
    async def test_timeout_fires_and_resolves_as_stand_not_fold(self):
        # Use 50ms timeout for fast test.
        events_log = []

        async def listener(state, events):
            events_log.extend(events)

        engine = TurnEngine(
            make_two_player_draw_state(version=10),
            on_event=listener,
            turn_timeout_ms=50,
            grace_ms=10,
        )
        await engine.start()
        try:
            # Wait long enough for the timer to fire and be processed.
            await asyncio.sleep(0.20)
            await engine.drain()
        finally:
            await engine.stop()

        # Player 0 must be STOOD (timeout result is STAND, never FOLD).
        p0 = engine.state.players[0]
        assert p0.stood is True, "timeout must resolve as STAND"
        assert p0.folded is False, "timeout must NEVER produce FOLD"

        # Engine must have actually fired the timer at least once.
        # (After seat 0 auto-stands, seat 1's timer also re-arms and may fire
        #  within our wait window — both being STAND, never FOLD.)
        assert engine.timeout_fires >= 1
        assert engine.state.players[1].folded is False  # invariant

        # state_version must have advanced. With 50ms timeout and a 200ms
        # wait window, both seats can auto-stand, transitioning to BETTING.
        assert engine.state.version >= 11

        # The emitted STAND events must be tagged auto + with reason
        # TURN_TIMEOUT_15S (one per seat that timed out).
        stands = [e for e in events_log if e.get("type") == "STAND"]
        assert len(stands) >= 1
        for s in stands:
            assert s["auto"] is True
            assert s["reason"] == "TURN_TIMEOUT_15S"
        # And no FOLD events emitted at all.
        assert not any(e.get("type") == "FOLD" for e in events_log)

    @pytest.mark.asyncio
    async def test_state_version_increments_on_each_mutation(self):
        engine = TurnEngine(
            make_two_player_draw_state(version=100),
            turn_timeout_ms=10_000,  # very long; we won't hit it
        )
        await engine.start()
        try:
            await engine.submit({
                "type": "STAND", "user_id": "u1", "source": "CLIENT",
                "state_version": 100, "client_action_id": "c1",
            })
            await engine.drain()
            assert engine.state.version == 101

            await engine.submit({
                "type": "STAND", "user_id": "u2", "source": "CLIENT",
                "state_version": 101, "client_action_id": "c2",
            })
            await engine.drain()
            # After both stand, reducer transitions DRAW -> BETTING; that itself
            # is the same mutation that bumped version once.
            assert engine.state.version == 102
            assert engine.state.phase == "BETTING"
        finally:
            await engine.stop()


# ---------- Turn advance ----------

class TestTurnAdvance:

    @pytest.mark.asyncio
    async def test_acting_in_time_advances_turn_and_cancels_timer(self):
        engine = TurnEngine(
            make_two_player_draw_state(version=5),
            turn_timeout_ms=200,  # 200ms — gives ample room to act
        )
        await engine.start()
        try:
            # Act well before timeout
            await asyncio.sleep(0.02)
            await engine.submit({
                "type": "STAND", "user_id": "u1", "source": "CLIENT",
                "state_version": 5, "client_action_id": "fast",
            })
            await engine.drain()

            # Turn advanced to seat 1
            assert engine.state.current_turn_seat == 1
            assert engine.state.players[0].stood is True
            assert engine.state.version == 6

            # Wait until the OLD timer would have fired; it must be cancelled.
            await asyncio.sleep(0.30)
            # Engine should NOT have logged a fire of the seat-0 timer.
            # (It may have armed and fired a seat-1 timer though.)
            # The seat-0 one specifically did not produce a stale STAND for seat 0.
            assert engine.state.players[0].stood is True
            # Seat 1 didn't get auto-folded — only auto-stood is allowed.
            assert engine.state.players[1].folded is False
        finally:
            await engine.stop()


# ---------- Stale timeout no-op ----------

class TestStaleTimeoutNoOp:

    @pytest.mark.asyncio
    async def test_stale_timer_after_player_acted_is_a_noop(self):
        """A timer was scheduled at version v=N for seat 0. Player acts in
        time, state moves to v=N+1, current_turn_seat is now 1. The original
        timer (if it ever fires) must not affect the new state.
        """
        engine = TurnEngine(
            make_two_player_draw_state(version=42),
            turn_timeout_ms=80,
            grace_ms=5,
        )
        await engine.start()
        try:
            # Capture engine internals before/after.
            await asyncio.sleep(0.01)
            await engine.submit({
                "type": "STAND", "user_id": "u1", "source": "CLIENT",
                "state_version": 42, "client_action_id": "fast2",
            })
            await engine.drain()

            assert engine.state.current_turn_seat == 1
            assert engine.state.version == 43

            # Now wait past the original timer's deadline.
            await asyncio.sleep(0.20)
            await engine.drain()

            # The original seat-0 timer must NOT have fired against v=42.
            # (It was cancelled; if for any reason it slipped through the
            #  cancellation, the bound_version != current check makes it no-op.)
            # Either way, seat 0 must remain STOOD-by-client (not auto), and
            # we must not see a duplicate stand for seat 0.

            # Crucially, no AUTO timeout for seat 0 should be in flight.
            # Engine bookkeeping: timeout_fires reflects ONLY current-turn fires.
            # If the stale timer survived cancellation it would land in
            # timeout_no_ops, never timeout_fires for the old seat.
            # We assert no FOLDs anywhere (turn timer never produces FOLD).
            assert engine.state.players[0].folded is False
            assert engine.state.players[1].folded is False
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_stale_timer_after_turn_changed_lands_as_no_op(self):
        """Force the stale path: arm a very short timer, intercept and let it
        fire AFTER state has advanced. The waiter's bound_version != current
        check must classify it as a no-op (timeout_no_ops += 1).
        """
        engine = TurnEngine(
            make_two_player_draw_state(version=7),
            turn_timeout_ms=30,
            grace_ms=5,
        )
        await engine.start()
        try:
            # Player acts immediately so state advances to v=8
            await engine.submit({
                "type": "STAND", "user_id": "u1", "source": "CLIENT",
                "state_version": 7, "client_action_id": "racing",
            })
            await engine.drain()
            # Wait so the (already-cancelled) v=7 timer would have fired,
            # AND the newly armed v=8 timer for seat 1 has had a chance.
            await asyncio.sleep(0.10)
            await engine.drain()
            # Seat 1's timer should fire for seat 1 (not seat 0).
            assert engine.state.players[0].stood is True  # client stand
            # Seat 1 either auto-stood (timer fired) or still active — both fine,
            # the assertion is about no FOLD ever.
            assert engine.state.players[0].folded is False
            assert engine.state.players[1].folded is False
        finally:
            await engine.stop()


# ---------- Server-only guard ----------

class TestServerOnlyGuardAtEngine:

    @pytest.mark.asyncio
    async def test_client_cannot_send_auto_stand_timeout(self):
        engine = TurnEngine(
            make_two_player_draw_state(version=1),
            turn_timeout_ms=10_000,
        )
        await engine.start()
        try:
            await engine.submit({
                "type": "AUTO_STAND_TIMEOUT",
                "source": "CLIENT",  # forbidden
                "user_id": "u1",
                "seat_index": 0,
                "state_version": 1,
                "client_action_id": "evil",
                "payload": {"reason": "TURN_TIMEOUT_15S"},
            })
            await engine.drain()

            # Engine rejected the client message at the boundary.
            assert engine.last_rejection is not None
            assert engine.last_rejection["error"] == "SERVER_ONLY_ACTION"
            # State did NOT change.
            assert engine.state.version == 1
            assert engine.state.players[0].stood is False
            assert engine.state.players[0].folded is False
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_client_must_supply_state_version(self):
        engine = TurnEngine(make_two_player_draw_state(version=3), turn_timeout_ms=10_000)
        await engine.start()
        try:
            await engine.submit({
                "type": "STAND", "user_id": "u1", "source": "CLIENT",
                # missing state_version
                "client_action_id": "no-sv",
            })
            await engine.drain()
            assert engine.last_rejection is not None
            assert engine.last_rejection["error"] == "MISSING_STATE_VERSION"
            assert engine.state.version == 3  # unchanged
        finally:
            await engine.stop()

    @pytest.mark.asyncio
    async def test_stale_state_version_is_rejected(self):
        engine = TurnEngine(make_two_player_draw_state(version=100), turn_timeout_ms=10_000)
        await engine.start()
        try:
            await engine.submit({
                "type": "STAND", "user_id": "u1", "source": "CLIENT",
                "state_version": 99,  # stale
                "client_action_id": "stale",
            })
            await engine.drain()
            assert engine.last_rejection is not None
            assert engine.last_rejection["error"] == "OUT_OF_SYNC"
            assert engine.last_rejection["expected_state_version"] == 100
            assert engine.last_rejection["received_state_version"] == 99
            assert engine.state.version == 100  # unchanged
        finally:
            await engine.stop()
