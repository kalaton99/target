"""Phase 6 — FastAPI binding for the realtime_v2 gateway.

Thin adapter that:
  - constructs a single Gatekeeper + PubSub + WebSocketGateway,
  - exposes a WS route at  POST  /v2/ws/table/{table_id}?token=<jwt>,
  - exposes a GET   /v2/realtime/health for ops.

FastAPI's `WebSocket` already satisfies our `WebSocketLike` protocol
(it has accept/close/send_json/receive_json), so no per-message
translation is needed.

Pure transport wiring. No engine logic, no auth logic — both are
injected from the application root (server.py).
"""
from __future__ import annotations

from typing import Awaitable, Callable, Dict, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from .gatekeeper import Gatekeeper
from .gateway import WebSocketGateway
from .pubsub import PubSub

# Re-export typing aliases for clarity at call site.
Authenticator = Callable[[str], Awaitable[Optional[str]]]
StateVersionProvider = Callable[[str], Awaitable[Optional[int]]]
ActionHandler = Callable[
    [str, str, str, Dict, int],
    Awaitable[Dict],
]


class RealtimeV2:
    """Bundle of singletons + helper to build the FastAPI router.

    Holding the Gatekeeper, PubSub, and Gateway as attributes makes
    them addressable from server code (e.g. for engine → broadcast)
    without going through globals.
    """

    def __init__(
        self,
        *,
        authenticate: Authenticator,
        get_state_version: StateVersionProvider,
        handle_action: ActionHandler,
        get_snapshot=None,
        on_connect=None,
        on_disconnect=None,
        max_per_user: int = 2,
        max_per_ip: int = 8,
        ping_interval: float = 15.0,
        ping_timeout: float = 10.0,
    ) -> None:
        self.gatekeeper = Gatekeeper(
            max_per_user=max_per_user, max_per_ip=max_per_ip,
        )
        self.pubsub = PubSub()
        self.gateway = WebSocketGateway(
            gatekeeper=self.gatekeeper,
            pubsub=self.pubsub,
            authenticate=authenticate,
            get_state_version=get_state_version,
            handle_action=handle_action,
            get_snapshot=get_snapshot,
            on_connect=on_connect,
            on_disconnect=on_disconnect,
            ping_interval=ping_interval,
            ping_timeout=ping_timeout,
        )

    def build_router(self) -> APIRouter:
        router = APIRouter(prefix="/v2", tags=["realtime_v2"])

        @router.get("/realtime/health")
        async def realtime_health():
            return {
                "status": "ok",
                "subsystem": "realtime_v2",
                "active_connections": self.gatekeeper.total(),
                "max_per_user": self.gatekeeper.max_per_user,
                "max_per_ip": self.gatekeeper.max_per_ip,
            }

        @router.websocket("/ws/table/{table_id}")
        async def ws_table(
            websocket: WebSocket,
            table_id: str,
            token: str = Query("", description="JWT bearer token"),
        ):
            ip = "0.0.0.0"
            if websocket.client and websocket.client.host:
                ip = websocket.client.host
            try:
                await self.gateway.handle(
                    websocket, token=token, table_id=table_id, ip=ip,
                )
            except WebSocketDisconnect:
                pass
            except Exception:  # noqa: BLE001
                # Defense in depth — gateway already handles cleanup
                pass

        return router


def build_v2_router(
    *,
    authenticate: Authenticator,
    get_state_version: StateVersionProvider,
    handle_action: ActionHandler,
    max_per_user: int = 2,
    max_per_ip: int = 8,
    ping_interval: float = 15.0,
    ping_timeout: float = 10.0,
) -> APIRouter:
    """Convenience: construct a `RealtimeV2` and return its router."""
    rt = RealtimeV2(
        authenticate=authenticate,
        get_state_version=get_state_version,
        handle_action=handle_action,
        max_per_user=max_per_user,
        max_per_ip=max_per_ip,
        ping_interval=ping_interval,
        ping_timeout=ping_timeout,
    )
    router = rt.build_router()
    # Attach for ops/test introspection.
    router.realtime_v2 = rt  # type: ignore[attr-defined]
    return router
