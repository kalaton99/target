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
    # Special card actions — DRAW-phase intents the engine handles via
    # reducer.reduce(). The active engine names are PLAY_TWO (defense / manual
    # transfer when holding 2H/2C) and PLAY_TEN (attack when holding 10H/10C).
    # ATTACK / PROTECT were earlier placeholder names; kept for backward
    # compatibility with any older client builds in the wild.
    "PLAY_TWO",
    "PLAY_TEN",
    "ATTACK",
    "PROTECT",
    # 2026-05 v2 — provably-fair RNG: per-seat client_seed contribution.
    # Reducer enforces phase whitelist (WAITING/PAYOUT/ENDED only)
    # and validates payload shape — gateway just allow-lists the type.
    "SUBMIT_CLIENT_SEED",
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
