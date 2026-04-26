"""Phase 6 — WebSocket message protocol.

Constants and tiny helpers only. No I/O, no state.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet

# ----------------------------------------------------------------------
# Allowed client → server intent types.
#
# This whitelist is intentionally narrow. The realtime layer does NOT
# decide what the engine accepts — it only decides what is even allowed
# to reach the engine. The engine enforces phase / turn / amount rules.
# ----------------------------------------------------------------------
CLIENT_ACTIONS: FrozenSet[str] = frozenset({
    # Draw phase
    "HIT",
    "STAND",
    # Betting phase
    "BET",
    "RAISE",
    "CALL",
    "CHECK",
    "FOLD",
    # Special card actions (placeholders for later phases; allowed here)
    "ATTACK",
    "PROTECT",
    # Heartbeat
    "PING",
    "PONG",
})

# ----------------------------------------------------------------------
# Server-only message types. If a client transmits any of these, the
# connection is treated as hostile / buggy and closed.
# ----------------------------------------------------------------------
SERVER_ONLY_TYPES: FrozenSet[str] = frozenset({
    "WELCOME",
    "STATE_UPDATE",
    "HAND_RESULT",
    "PHASE_CHANGED",
    "TURN_TIMEOUT",
    "ERROR",
    "OUT_OF_SYNC",
    "FRESH_STATE",
    "ACTION_ACK",
})

# Standard close codes (RFC 6455).
CLOSE_NORMAL = 1000
CLOSE_POLICY_VIOLATION = 1008
CLOSE_INTERNAL_ERROR = 1011


def make_error(code: str, message: str = "", **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": "ERROR", "code": code, "message": message}
    out.update(extra)
    return out


def make_out_of_sync(received: int, current: int) -> Dict[str, Any]:
    return {
        "type": "OUT_OF_SYNC",
        "received_state_version": received,
        "current_state_version": current,
    }


def make_welcome(user_id: str, table_id: str, state_version: int) -> Dict[str, Any]:
    return {
        "type": "WELCOME",
        "user_id": user_id,
        "table_id": table_id,
        "state_version": state_version,
    }
