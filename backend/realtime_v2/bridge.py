"""Phase 6 — Engine ↔ Realtime bridge.

Wires `TurnEngine` instances to the realtime_v2 PubSub:

  Inbound  : gateway → bridge.handle_action → engine.submit (FIFO)
  Outbound : engine.on_event → bridge._publish_state → pubsub("table:{id}")

The bridge owns:
  - a `Dict[table_id, TurnEngine]` registry,
  - a per-table asyncio.Lock (so concurrent client actions for the same
    table are serialized into the engine queue in a known order),
  - per-intent asyncio.Future plumbing so `handle_action` can deterministically
    return success / rejection without racing the engine's serial loop or
    server-fired AUTO_STAND_TIMEOUT events.

Public surface used by the gateway:
  - `get_state_version(table_id) -> int | None`
  - `handle_action(table_id, user_id, action, payload, sv) -> dict`
  - `notify_connect(table_id, user_id)`     — Phase 11 P1 reconnect grace
  - `notify_disconnect(table_id, user_id)`  — Phase 11 P1 reconnect grace

The connect/disconnect hooks let the bridge maintain per-(table, user)
presence: while a player is mid-disconnect we keep their seat and let
the existing engine timers run (so AUTO_STAND_TIMEOUT still fires on a
disconnected current-turn seat). After `grace_seconds` of silence we
mark `player.sitting_out = True` so subsequent hands skip them. A
reconnect inside the grace window cancels the timer and flips
`connected` back to True without any state-machine side effects.

Both of those are bound as the gateway's injected callables.

Server-only intents (AUTO_STAND_TIMEOUT, etc.) NEVER come through
`handle_action` — they are produced by the engine's own internal timer
with `source="SERVER"`. The reducer rejects any client-originated
server-only intent. The gateway also rejects them at the protocol layer.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from game_engine.turn_engine import TurnEngine
from game_engine.types import GameState

from .pubsub import PubSub


# ---------- public broadcast envelope ----------

def _public_state_payload(table_id: str, state: GameState, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Minimal, privacy-safe state snapshot for broadcast.

    Cards are NOT exposed in the broadcast (face-down for everyone). A
    per-viewer PRIVATE_STATE message is sent separately to each player
    on their dedicated `table:{id}:user:{user_id}` topic.
    """
    return {
        "type": "STATE_UPDATE",
        "table_id": table_id,
        "state_version": state.version,
        "phase": state.phase,
        "hand_id": state.hand_id,
        "hand_number": state.hand_number,
        "target_score": state.target_score,
        "current_turn_seat": state.current_turn_seat,
        "turn_started_at_ms": state.turn_started_at_ms,
        "turn_deadline_ms": state.turn_deadline_ms,
        "pot": state.pot,
        "current_call_owed": state.current_call_owed,
        "last_raise_amount": state.last_raise_amount,
        "betting_round": state.betting_round,
        "winners": list(state.winners),
        "players": [
            {
                "seat": p.seat_index,
                "user_id": p.user_id,
                "username": p.username,
                "score": p.score,
                "soft": p.soft,
                "current_bet": p.current_bet,
                "total_contributed": p.total_contributed,
                "available_balance": p.available_balance(),
                "card_count": len(p.cards),
                "busted": p.busted,
                "stood": p.stood,
                "folded": p.folded,
                "disqualified": p.disqualified,
                "sitting_out": p.sitting_out,
                "connected": p.connected,
                "payout": p.payout,
            }
            for p in state.players
        ],
        "events": list(events),
        "last_action": state.last_action_summary,
    }


def _private_state_payload(table_id: str, state: GameState, player) -> Dict[str, Any]:
    """Per-viewer private envelope. Carries the viewer's face-up cards
    plus a tag binding it to a specific state_version for ordering with
    public STATE_UPDATEs on the client side.
    """
    return {
        "type": "PRIVATE_STATE",
        "table_id": table_id,
        "state_version": state.version,
        "user_id": player.user_id,
        "seat": player.seat_index,
        "cards": list(player.cards),
        "score": player.score,
        "soft": player.soft,
        "busted": player.busted,
        "disqualified": player.disqualified,
    }


# ---------- internal: per-intent completion tracking ----------

def _install_intent_tracking(engine: TurnEngine) -> Dict[str, asyncio.Future]:
    """Wrap `engine._process` so each processed intent resolves a future
    keyed by `client_action_id`. The resolution payload tells the bridge
    whether the action was accepted (and at which version) or rejected.

    Resilient to engine `last_rejection` reuse: we capture pre/post
    `state.version` and `last_rejection` snapshots inside the wrapper.
    """
    pending: Dict[str, asyncio.Future] = {}
    original_process = engine._process

    async def tracked_process(intent: Dict[str, Any]) -> None:
        cid = intent.get("client_action_id")
        pre_version = engine.state.version
        # Snapshot rejection BEFORE processing so we can detect a fresh one.
        pre_rejection_id = (
            engine.last_rejection.get("client_action_id")
            if engine.last_rejection else None
        )
        try:
            await original_process(intent)
        finally:
            if cid:
                fut = pending.pop(cid, None)
                if fut is not None and not fut.done():
                    rej = engine.last_rejection
                    if (
                        rej is not None
                        and rej.get("client_action_id") == cid
                        and pre_rejection_id != cid
                    ):
                        fut.set_result({"accepted": False, "error": dict(rej)})
                    elif engine.state.version > pre_version:
                        fut.set_result({
                            "accepted": True,
                            "state_version": engine.state.version,
                        })
                    else:
                        fut.set_result({
                            "accepted": False,
                            "error": {"reason": "UNCHANGED"},
                        })

    engine._process = tracked_process  # type: ignore[method-assign]
    return pending


# ---------- bridge ----------

OnPublish = Callable[[str, Dict[str, Any]], Awaitable[None]]


class EngineBridge:
    """Per-process registry connecting `TurnEngine`s to the realtime PubSub."""

    # Reconnect-grace bounds (seconds). The PRD specifies 20–30s; we clamp
    # to that range and default to 25s. The cap is there so a buggy caller
    # cannot stall sitting_out indefinitely.
    GRACE_MIN = 20.0
    GRACE_MAX = 30.0
    GRACE_DEFAULT = 25.0

    def __init__(
        self,
        pubsub: PubSub,
        *,
        ack_timeout: float = 2.0,
        grace_seconds: float = GRACE_DEFAULT,
    ) -> None:
        self._pubsub = pubsub
        self._engines: Dict[str, TurnEngine] = {}
        self._pending: Dict[str, Dict[str, asyncio.Future]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._ack_timeout = float(ack_timeout)
        # Clamp grace_seconds into [GRACE_MIN, GRACE_MAX] per PRD.
        gs = float(grace_seconds)
        if gs < self.GRACE_MIN:
            gs = self.GRACE_MIN
        elif gs > self.GRACE_MAX:
            gs = self.GRACE_MAX
        self._grace_seconds = gs
        # (table_id, user_id) -> asyncio.Task running the grace expiry.
        self._grace_tasks: Dict[tuple, asyncio.Task] = {}

    # ---- engine lifecycle ----

    def register_engine(self, table_id: str, engine: TurnEngine) -> None:
        """Bind an engine: install on_event broadcaster + intent tracking.

        The engine should NOT already have an `on_event` callback — the
        bridge takes ownership.
        """
        if table_id in self._engines:
            raise ValueError(f"ENGINE_ALREADY_REGISTERED: {table_id}")

        async def _on_event(state: GameState, events: List[Dict[str, Any]]) -> None:
            await self._publish_state(table_id, state, events)

        engine._on_event = _on_event  # type: ignore[attr-defined]
        self._pending[table_id] = _install_intent_tracking(engine)
        self._engines[table_id] = engine
        self._locks[table_id] = asyncio.Lock()

    async def unregister_engine(self, table_id: str) -> None:
        engine = self._engines.pop(table_id, None)
        self._pending.pop(table_id, None)
        self._locks.pop(table_id, None)
        # Cancel any in-flight grace timers for this table.
        for key in list(self._grace_tasks.keys()):
            if key[0] == table_id:
                task = self._grace_tasks.pop(key, None)
                if task is not None and not task.done():
                    task.cancel()
        if engine is not None:
            await engine.stop()

    def has_engine(self, table_id: str) -> bool:
        return table_id in self._engines

    def snapshot(self, table_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Return the catch-up messages a freshly-connecting client needs:
            [public STATE_UPDATE,  PRIVATE_STATE for `user_id` if seated]

        Empty list if the table has no engine. The list is safe to send
        in order before any further pubsub broadcasts.
        """
        engine = self._engines.get(table_id)
        if engine is None:
            return []
        state = engine.state
        out: List[Dict[str, Any]] = [_public_state_payload(table_id, state, [])]
        for p in state.players:
            if p.user_id == user_id:
                out.append(_private_state_payload(table_id, state, p))
                break
        return out

    # ---- gateway-facing callables ----

    async def get_state_version(self, table_id: str) -> Optional[int]:
        engine = self._engines.get(table_id)
        return None if engine is None else engine.state.version

    async def handle_action(
        self,
        table_id: str,
        user_id: str,
        action_type: str,
        payload: Dict[str, Any],
        state_version: int,
    ) -> Dict[str, Any]:
        engine = self._engines.get(table_id)
        if engine is None:
            return {"accepted": False, "error": "TABLE_NOT_FOUND"}

        cid = uuid.uuid4().hex
        intent: Dict[str, Any] = {
            "type": action_type,
            "user_id": user_id,
            "state_version": state_version,
            "payload": payload,
            "source": "CLIENT",
            "client_action_id": cid,
        }

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[table_id][cid] = fut

        async with self._locks[table_id]:
            await engine.submit(intent)

        try:
            return await asyncio.wait_for(fut, timeout=self._ack_timeout)
        except asyncio.TimeoutError:
            self._pending[table_id].pop(cid, None)
            return {"accepted": False, "error": {"reason": "ENGINE_TIMEOUT"}}

    # ---- presence / reconnect-grace ----

    @property
    def grace_seconds(self) -> float:
        """Configured reconnect-grace window (clamped to 20-30s)."""
        return self._grace_seconds

    def _find_player(self, table_id: str, user_id: str):
        """Return (engine, player_state) for the seated user, or (None, None)."""
        engine = self._engines.get(table_id)
        if engine is None:
            return None, None
        for p in engine.state.players:
            if p.user_id == user_id:
                return engine, p
        return engine, None

    async def notify_connect(self, table_id: str, user_id: str) -> None:
        """Mark the user as connected; cancel any in-flight grace timer.

        Called by the gateway right after a successful WS handshake. Safe
        to call for users who are not currently disconnected — it's a
        no-op in that case (no broadcast).
        """
        # Always cancel a pending grace timer for this user.
        task = self._grace_tasks.pop((table_id, user_id), None)
        if task is not None and not task.done():
            task.cancel()

        engine, player = self._find_player(table_id, user_id)
        if engine is None or player is None:
            return
        if player.connected:
            return  # already connected; nothing to broadcast.
        player.connected = True
        # Re-broadcast presence so other clients see them online again.
        # We use a synthetic PRESENCE event so the UI can surface it
        # alongside the regular STATE_UPDATE stream.
        await self._publish_state(
            table_id,
            engine.state,
            [{
                "type": "PRESENCE",
                "user_id": user_id,
                "seat": player.seat_index,
                "connected": True,
                "sitting_out": player.sitting_out,
            }],
        )

    async def notify_disconnect(self, table_id: str, user_id: str) -> None:
        """Mark the user as disconnected and start a grace timer.

        Called by the gateway when a WS session ends (close, error, idle
        timeout, or abnormal). The seat is preserved during grace; the
        existing engine 15s turn timer is unaffected, so a disconnected
        current-turn seat will still trigger AUTO_STAND_TIMEOUT.
        """
        engine, player = self._find_player(table_id, user_id)
        if engine is None or player is None:
            return
        # Start (or refresh) a grace timer regardless of current connected
        # flag: an orderly close-then-reopen could otherwise leak a stale
        # task on the table_id/user_id key.
        prior = self._grace_tasks.pop((table_id, user_id), None)
        if prior is not None and not prior.done():
            prior.cancel()

        if player.connected:
            player.connected = False
            await self._publish_state(
                table_id,
                engine.state,
                [{
                    "type": "PRESENCE",
                    "user_id": user_id,
                    "seat": player.seat_index,
                    "connected": False,
                    "sitting_out": player.sitting_out,
                    "grace_seconds": self._grace_seconds,
                }],
            )

        loop = asyncio.get_event_loop()
        task = loop.create_task(self._grace_expiry(table_id, user_id))
        self._grace_tasks[(table_id, user_id)] = task

    async def _grace_expiry(self, table_id: str, user_id: str) -> None:
        """Sleep `grace_seconds` then mark the player sitting_out=True.

        The wait is cancellable: a `notify_connect` inside the window
        cancels the task and the player keeps their seat with no further
        side effects. If the engine is unregistered mid-sleep we exit
        cleanly without touching state.
        """
        try:
            await asyncio.sleep(self._grace_seconds)
        except asyncio.CancelledError:
            return
        # Re-resolve the player; the table or seat may have gone away.
        engine, player = self._find_player(table_id, user_id)
        # Drop our own task entry first so re-entrant calls (if any) work.
        self._grace_tasks.pop((table_id, user_id), None)
        if engine is None or player is None:
            return
        if player.sitting_out:
            return  # already sitting out; nothing to do.
        player.sitting_out = True
        # `connected` stays False; the gateway will flip it back on
        # reconnect via notify_connect.
        await self._publish_state(
            table_id,
            engine.state,
            [{
                "type": "PRESENCE_GRACE_EXPIRED",
                "user_id": user_id,
                "seat": player.seat_index,
                "connected": False,
                "sitting_out": True,
            }],
        )

    # ---- internal ----

    async def _publish_state(
        self, table_id: str, state: GameState, events: List[Dict[str, Any]],
    ) -> None:
        # 1) Public broadcast — face-down cards for everyone.
        public = _public_state_payload(table_id, state, events)
        await self._pubsub.publish(f"table:{table_id}", public)

        # 2) Per-viewer unicast — each player gets their own face-up cards
        #    on their dedicated topic. No other player can subscribe to it.
        for p in state.players:
            if p.sitting_out:
                continue
            priv = _private_state_payload(table_id, state, p)
            await self._pubsub.publish(
                f"table:{table_id}:user:{p.user_id}", priv,
            )
