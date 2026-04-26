"""Phase 6 — WebSocket gateway.

Single coroutine `WebSocketGateway.handle(...)` wraps the lifetime of one
client connection. Responsibilities:

  1. Authenticate via injected `authenticate(token) -> user_id | None`.
  2. Reserve a connection slot via Gatekeeper (per-user + per-IP caps).
  3. Subscribe to the table's pub/sub topic and pump broadcasts to ws.
  4. Read client intents, validating:
       - shape  (must be a dict)
       - type   (must be in CLIENT_ACTIONS, never in SERVER_ONLY_TYPES)
       - state_version  (required, must equal current per provider)
  5. Forward valid intents to `handle_action(...)` and ack the result.
  6. Maintain ping/pong heartbeat; close on missed pong.
  7. On any exit path, release pub/sub subscription, gatekeeper slot,
     and close the underlying socket.

Transport-agnostic by design: any object satisfying `WebSocketLike` works,
including FastAPI WebSocket and the in-test `FakeWebSocket`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol, runtime_checkable

from .gatekeeper import Gatekeeper, IpCapExceeded, UserCapExceeded
from .protocol import (
    CLIENT_ACTIONS,
    CLOSE_NORMAL,
    CLOSE_POLICY_VIOLATION,
    SERVER_ONLY_TYPES,
    make_error,
    make_out_of_sync,
    make_welcome,
)
from .pubsub import PubSub

logger = logging.getLogger("realtime_v2.gateway")


# ---------- transport contract ----------

@runtime_checkable
class WebSocketLike(Protocol):
    async def accept(self) -> None: ...
    async def close(self, code: int = 1000) -> None: ...
    async def send_json(self, data: Any) -> None: ...
    async def receive_json(self) -> Any: ...


# ---------- injected callable signatures ----------

# (token) -> user_id | None
Authenticator = Callable[[str], Awaitable[Optional[str]]]
# (table_id) -> current state_version | None (None means "table not found")
StateVersionProvider = Callable[[str], Awaitable[Optional[int]]]
# (table_id, user_id, action_type, payload, state_version) -> result dict
ActionHandler = Callable[
    [str, str, str, Dict[str, Any], int],
    Awaitable[Dict[str, Any]],
]
# Optional: (table_id, user_id) -> [catch-up messages] sent right after WELCOME
SnapshotProvider = Callable[[str, str], list]


# ---------- gateway ----------

class WebSocketGateway:
    """Owns the per-connection state machine."""

    def __init__(
        self,
        *,
        gatekeeper: Gatekeeper,
        pubsub: PubSub,
        authenticate: Authenticator,
        get_state_version: StateVersionProvider,
        handle_action: ActionHandler,
        get_snapshot: Optional[SnapshotProvider] = None,
        ping_interval: float = 15.0,
        ping_timeout: float = 10.0,
    ) -> None:
        self._gk = gatekeeper
        self._ps = pubsub
        self._authenticate = authenticate
        self._get_state_version = get_state_version
        self._handle_action = handle_action
        self._get_snapshot = get_snapshot
        self._ping_interval = float(ping_interval)
        self._ping_timeout = float(ping_timeout)

    # -------- public entry point --------

    async def handle(
        self,
        ws: WebSocketLike,
        *,
        token: str,
        table_id: str,
        ip: str,
    ) -> None:
        # 1) Auth before consuming a slot.
        user_id = await self._authenticate(token)
        if not user_id:
            await self._reject(ws, make_error("AUTH_FAILED", "invalid or expired token"))
            return

        # 2) Acquire connection slot.
        try:
            slot_token = await self._gk.acquire(user_id, ip)
        except UserCapExceeded:
            await self._reject(ws, make_error("USER_CAP_EXCEEDED"))
            return
        except IpCapExceeded:
            await self._reject(ws, make_error("IP_CAP_EXCEEDED"))
            return

        table_topic = f"table:{table_id}"
        user_topic = f"table:{table_id}:user:{user_id}"
        table_queue = await self._ps.subscribe(table_topic)
        user_queue = await self._ps.subscribe(user_topic)
        accepted = False
        try:
            await ws.accept()
            accepted = True
            # Send welcome with the current state_version.
            sv = await self._get_state_version(table_id)
            await ws.send_json(make_welcome(user_id, table_id, sv if sv is not None else 0))

            # Send catch-up snapshot so the client receives the current
            # state even if it connected after the most recent broadcast.
            if self._get_snapshot is not None:
                try:
                    snap = self._get_snapshot(table_id, user_id) or []
                except Exception:  # noqa: BLE001
                    snap = []
                for msg in snap:
                    try:
                        await ws.send_json(msg)
                    except Exception:  # noqa: BLE001
                        break

            await self._run_session(
                ws=ws,
                user_id=user_id,
                table_id=table_id,
                queues=[table_queue, user_queue],
            )
        finally:
            await self._ps.unsubscribe(table_topic, table_queue)
            await self._ps.unsubscribe(user_topic, user_queue)
            await self._gk.release(slot_token)
            try:
                if accepted:
                    await ws.close(CLOSE_NORMAL)
            except Exception:
                pass

    # -------- internals --------

    async def _reject(self, ws: WebSocketLike, error: Dict[str, Any]) -> None:
        try:
            await ws.accept()
            await ws.send_json(error)
        except Exception:
            pass
        try:
            await ws.close(CLOSE_POLICY_VIOLATION)
        except Exception:
            pass

    async def _run_session(
        self,
        *,
        ws: WebSocketLike,
        user_id: str,
        table_id: str,
        queues: list,
    ) -> None:
        loop = asyncio.get_event_loop()
        stop = asyncio.Event()
        # `last_pong` is a 1-element list so inner closures can mutate it.
        last_pong = [loop.time()]

        # Fan-in: merge multiple subscription queues into one out-stream.
        out_queue: asyncio.Queue = asyncio.Queue()

        async def fan_in(src: asyncio.Queue) -> None:
            try:
                while not stop.is_set():
                    try:
                        msg = await src.get()
                    except asyncio.CancelledError:
                        return
                    await out_queue.put(msg)
            finally:
                pass

        async def reader() -> None:
            try:
                while not stop.is_set():
                    try:
                        msg = await ws.receive_json()
                    except Exception:
                        # Disconnect or transport error
                        return
                    await self._dispatch_inbound(
                        ws=ws,
                        user_id=user_id,
                        table_id=table_id,
                        msg=msg,
                        last_pong=last_pong,
                        stop=stop,
                    )
            finally:
                stop.set()

        async def writer() -> None:
            try:
                while not stop.is_set():
                    try:
                        message = await asyncio.wait_for(out_queue.get(), timeout=0.25)
                    except asyncio.TimeoutError:
                        continue
                    try:
                        await ws.send_json(message)
                    except Exception:
                        return
            finally:
                stop.set()

        async def heartbeat() -> None:
            try:
                while not stop.is_set():
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=self._ping_interval)
                        return  # stop set
                    except asyncio.TimeoutError:
                        pass
                    # Check pong freshness.
                    if loop.time() - last_pong[0] > (self._ping_interval + self._ping_timeout):
                        try:
                            await ws.send_json(make_error("PING_TIMEOUT"))
                        except Exception:
                            pass
                        return
                    try:
                        await ws.send_json({"type": "PING"})
                    except Exception:
                        return
            finally:
                stop.set()

        tasks = [
            asyncio.create_task(reader(), name="ws_reader"),
            asyncio.create_task(writer(), name="ws_writer"),
            asyncio.create_task(heartbeat(), name="ws_heartbeat"),
        ]
        for q in queues:
            tasks.append(asyncio.create_task(fan_in(q), name="ws_fanin"))
        try:
            await stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    async def _dispatch_inbound(
        self,
        *,
        ws: WebSocketLike,
        user_id: str,
        table_id: str,
        msg: Any,
        last_pong: list,
        stop: asyncio.Event,
    ) -> None:
        if not isinstance(msg, dict):
            await ws.send_json(make_error("BAD_MESSAGE", "expected JSON object"))
            stop.set()
            return

        mtype = msg.get("type")

        # Heartbeat: pong from client refreshes the deadline.
        if mtype == "PONG":
            last_pong[0] = asyncio.get_event_loop().time()
            return
        # Client-initiated PING: reply with PONG (server is the heartbeat
        # owner, but we accommodate to keep test/ops simple).
        if mtype == "PING":
            try:
                await ws.send_json({"type": "PONG"})
            except Exception:
                stop.set()
            return

        # Reject server-only types — these can never legitimately come from a client.
        if mtype in SERVER_ONLY_TYPES:
            await ws.send_json(make_error("SERVER_ONLY_TYPE", reject=mtype))
            stop.set()
            return

        if mtype not in CLIENT_ACTIONS:
            await ws.send_json(make_error("UNKNOWN_TYPE", reject=str(mtype)))
            return

        # state_version is required and must be an int (and not bool).
        sv = msg.get("state_version", None)
        if sv is None or isinstance(sv, bool) or not isinstance(sv, int):
            await ws.send_json(make_error("MISSING_STATE_VERSION"))
            return

        current = await self._get_state_version(table_id)
        if current is None:
            await ws.send_json(make_error("TABLE_NOT_FOUND"))
            return
        if sv != current:
            await ws.send_json(make_out_of_sync(sv, current))
            return

        payload = msg.get("payload") or {}
        if not isinstance(payload, dict):
            await ws.send_json(make_error("BAD_PAYLOAD"))
            return

        try:
            result = await self._handle_action(table_id, user_id, mtype, payload, sv)
        except Exception as exc:  # noqa: BLE001
            logger.exception("action handler error: table=%s user=%s type=%s", table_id, user_id, mtype)
            await ws.send_json(make_error("ACTION_FAILED", str(exc)))
            return

        await ws.send_json({
            "type": "ACTION_ACK",
            "action": mtype,
            "result": result,
        })
