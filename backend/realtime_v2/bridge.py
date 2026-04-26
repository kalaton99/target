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
        "current_turn_seat": state.current_turn_seat,
        "turn_started_at_ms": state.turn_started_at_ms,
        "turn_deadline_ms": state.turn_deadline_ms,
        "pot": state.pot,
        "current_bet": state.current_bet,
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

    def __init__(self, pubsub: PubSub, *, ack_timeout: float = 2.0) -> None:
        self._pubsub = pubsub
        self._engines: Dict[str, TurnEngine] = {}
        self._pending: Dict[str, Dict[str, asyncio.Future]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._ack_timeout = float(ack_timeout)

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
