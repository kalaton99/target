"""Phase 6 — Realtime WebSocket layer.

Pure, transport-agnostic primitives:
  - Gatekeeper:  per-user / per-IP connection caps
  - PubSub:      in-process topic-based broadcast
  - Protocol:    message types, server-only set, error envelopes
  - Gateway:     orchestrates auth, caps, ping/pong, state_version,
                 server-only rejection, and broadcast bridge

No coupling to FastAPI here; the FastAPI route is a thin wrapper added
when wiring this module into `server.py` (deferred until the user
authorizes Phase 11 / app-wiring).
"""

from .gatekeeper import Gatekeeper, UserCapExceeded, IpCapExceeded, GatekeeperError  # noqa: F401
from .pubsub import PubSub  # noqa: F401
from .gateway import WebSocketGateway, WebSocketLike  # noqa: F401
from .bridge import EngineBridge  # noqa: F401
from .protocol import (  # noqa: F401
    CLIENT_ACTIONS,
    SERVER_ONLY_TYPES,
    CLOSE_NORMAL,
    CLOSE_POLICY_VIOLATION,
    make_error,
    make_out_of_sync,
)
