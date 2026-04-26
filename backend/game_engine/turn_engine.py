"""Phase 3 — Turn engine.

Isolated, testable orchestration around the pure reducer.

Responsibilities (Phase 3 only):
  - Own a single GameState in-process.
  - Serialize incoming intents through a FIFO queue.
  - Authoritative 15-second turn timer:
      * Started when current_turn_seat is set (DRAW phase).
      * Cancelled when the active player acts in time.
      * Otherwise emits AUTO_STAND_TIMEOUT (source=SERVER, reason=TURN_TIMEOUT_15S).
  - Reject server-only intents from clients.
  - Reject stale state_version intents (OUT_OF_SYNC).
  - Increment state_version on every mutation (handled by the reducer).

Out of scope (deferred to later phases):
  - Persistence (no DB writes here).
  - WebSocket I/O (no sockets; broadcast is via an injected callback).
  - Wallet (no debits/credits).
  - Lobby, betting expansion, specials, etc.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .reducer import reduce as pure_reduce, ReducerError
from .types import GameState

# Re-export for convenience in tests
from core.constants import (
    TURN_TIMEOUT_MS,
    TURN_TIMEOUT_REASON,
    TIMEOUT_GRACE_MS,
    SERVER_ONLY_ACTIONS,
)


class TurnEngineError(Exception):
    pass


class TurnEngine:
    """Single-table turn engine.

    Args:
        state: initial GameState.
        on_event: optional async callback invoked with (state, events) after
            every successful mutation. Used by tests / future broadcaster.
        turn_timeout_ms: override (tests use a small value).
        grace_ms: timer wakes at deadline + grace to absorb scheduling jitter.
        clock_ms: zero-arg callable returning epoch ms (overridable for tests).
    """

    def __init__(
        self,
        state: GameState,
        *,
        on_event: Optional[Callable[[GameState, List[Dict[str, Any]]], Awaitable[None]]] = None,
        turn_timeout_ms: int = TURN_TIMEOUT_MS,
        grace_ms: int = TIMEOUT_GRACE_MS,
        clock_ms: Optional[Callable[[], int]] = None,
    ):
        self.state: GameState = state
        self._on_event = on_event
        self._timeout_ms = int(turn_timeout_ms)
        self._grace_ms = int(grace_ms)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))

        self._queue: asyncio.Queue = asyncio.Queue()
        self._loop_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()
        # Visibility for tests:
        self.last_rejection: Optional[Dict[str, Any]] = None
        self.timeout_fires: int = 0
        self.timeout_no_ops: int = 0

    # ---------------- lifecycle ----------------

    async def start(self) -> None:
        if self._loop_task is not None:
            return
        self._loop_task = asyncio.create_task(self._loop())
        # Arm initial timer if we're already on a turn.
        self._maybe_arm_timeout()

    async def stop(self) -> None:
        self._stopped.set()
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
            self._loop_task = None

    # ---------------- public API ----------------

    async def submit(self, intent: Dict[str, Any]) -> None:
        """Enqueue a client or server intent for serial processing."""
        await self._queue.put(intent)

    async def drain(self, timeout: float = 1.0) -> None:
        """Wait until the queue is empty (test helper)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.empty():
                # Give the loop a tick to finish processing in-flight item
                await asyncio.sleep(0)
                if self._queue.empty():
                    return
            await asyncio.sleep(0.005)

    # ---------------- internals ----------------

    async def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                intent = await self._queue.get()
            except asyncio.CancelledError:
                return
            await self._process(intent)

    async def _process(self, intent: Dict[str, Any]) -> None:
        # 1. Server-only action guard at engine boundary (defense in depth;
        #    the reducer also enforces this).
        a_type = intent.get("type")
        source = intent.get("source", "CLIENT")
        if a_type in SERVER_ONLY_ACTIONS and source != "SERVER":
            self._reject(intent, "SERVER_ONLY_ACTION")
            return

        # 2. state_version validation for client intents.
        if source != "SERVER":
            if "state_version" not in intent:
                self._reject(intent, "MISSING_STATE_VERSION")
                return
            if intent["state_version"] != self.state.version:
                self._reject(
                    intent,
                    "OUT_OF_SYNC",
                    extra={
                        "expected_state_version": self.state.version,
                        "received_state_version": intent["state_version"],
                    },
                )
                return

        # 3. Reduce.
        try:
            new_state, events = pure_reduce(self.state, intent)
        except ReducerError as exc:
            self._reject(intent, str(exc))
            return

        # 4. Hard invariant: a turn-timer-derived AUTO_STAND_TIMEOUT must
        #    NEVER convert into FOLD events. Auto-fold may only originate
        #    from betting-phase reducers (not exercised in Phase 3).
        if a_type == "AUTO_STAND_TIMEOUT":
            for ev in events:
                assert ev.get("type") != "FOLD", (
                    "INVARIANT_VIOLATION: turn timer must never produce FOLD"
                )

        # 5. Commit.
        self.state = new_state

        # 6. Re-arm or cancel the turn timer based on new state.
        self._cancel_timeout()
        self._maybe_arm_timeout()

        # 7. Notify external listeners.
        if self._on_event is not None:
            try:
                await self._on_event(self.state, events)
            except Exception:
                # Listeners must not break the engine.
                pass

    def _maybe_arm_timeout(self) -> None:
        """Arm the authoritative 15s timer if we are mid-turn in DRAW."""
        if self.state.phase != "DRAW":
            return
        if self.state.current_turn_seat is None:
            return
        # Stamp the deadline on the state so external observers (UI, tests)
        # can derive a countdown.
        now_ms = self._clock_ms()
        self.state.turn_started_at_ms = now_ms
        self.state.turn_deadline_ms = now_ms + self._timeout_ms

        bound_version = self.state.version
        bound_seat = self.state.current_turn_seat
        bound_user = self.state.players[bound_seat].user_id

        async def _waiter() -> None:
            try:
                await asyncio.sleep((self._timeout_ms + self._grace_ms) / 1000.0)
            except asyncio.CancelledError:
                return
            # Stale-fire check: if anything has changed, this timer is no-op.
            if (
                self.state.version != bound_version
                or self.state.current_turn_seat != bound_seat
                or self.state.phase != "DRAW"
            ):
                self.timeout_no_ops += 1
                return
            self.timeout_fires += 1
            await self._queue.put({
                "type": "AUTO_STAND_TIMEOUT",
                "source": "SERVER",
                "user_id": bound_user,
                "seat_index": bound_seat,
                "state_version": bound_version,
                "payload": {"reason": TURN_TIMEOUT_REASON, "source": "SERVER"},
            })

        self._timeout_task = asyncio.create_task(_waiter())

    def _cancel_timeout(self) -> None:
        if self._timeout_task is not None:
            self._timeout_task.cancel()
            self._timeout_task = None

    def _reject(self, intent: Dict[str, Any], error: str, extra: Optional[Dict[str, Any]] = None) -> None:
        rec = {
            "type": "ACTION_REJECTED",
            "client_action_id": intent.get("client_action_id"),
            "error": error,
        }
        if extra:
            rec.update(extra)
        self.last_rejection = rec
