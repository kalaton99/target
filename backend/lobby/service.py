"""Phase 11 P2 — Lobby service.

Mongo-backed table CRUD + lightweight guest auth (username only). Engines
themselves remain in-process inside `EngineBridge`; Mongo only stores
table metadata so multiple processes/sessions can list and join.

Lifecycle:
  LOBBY    — created, players joining
  RUNNING  — engine spawned, hand started; no further joins allowed
  ENDED   (not used in this MVP — engines unregister implicitly)
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.constants import (
    DEFAULT_TARGET_SCORE,
    MAX_PLAYERS,
    MIN_PLAYERS,
    VALID_TARGET_SCORES,
    min_seated_for_target,
    seats_for_target,
)


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,16}$")
_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{2,32}$")


class LobbyError(Exception):
    """Raised on any user-facing lobby validation error."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _now() -> float:
    return time.time()


# ============================================================
# User registration / lookup
# ============================================================

async def upsert_guest_user(db: AsyncIOMotorDatabase, username: str) -> Dict[str, Any]:
    """Get-or-create a guest user keyed by username. Returns
    {user_id, username, created_at} (no _id).
    """
    if not username or not _USERNAME_RE.match(username):
        raise LobbyError("INVALID_USERNAME", "letters/digits/_/-, 2–16 chars")
    doc = await db["lobby_users"].find_one({"username": username}, {"_id": 0})
    if doc:
        return doc
    user_id = f"u_{uuid.uuid4().hex[:12]}"
    new_doc = {
        "user_id": user_id,
        "username": username,
        "created_at": _now(),
    }
    await db["lobby_users"].insert_one(dict(new_doc))
    return new_doc


async def get_user(db: AsyncIOMotorDatabase, user_id: str) -> Optional[Dict[str, Any]]:
    return await db["lobby_users"].find_one({"user_id": user_id}, {"_id": 0})


# ============================================================
# Table CRUD
# ============================================================

def _public_table(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Strip Mongo internals + return broadcast-safe shape."""
    return {
        "table_id": doc["table_id"],
        "name": doc["name"],
        "creator_user_id": doc["creator_user_id"],
        "target_score": doc["target_score"],
        "stake": doc["stake"],
        "max_players": doc["max_players"],
        "min_players": doc["min_players"],
        "bot_count": int(doc.get("bot_count", 0)),
        "status": doc["status"],
        "seats": list(doc.get("seats", [])),
        "created_at": doc.get("created_at"),
        "started_at": doc.get("started_at"),
    }


async def create_table(
    db: AsyncIOMotorDatabase,
    *,
    creator_user_id: str,
    name: str,
    target_score: int = DEFAULT_TARGET_SCORE,
    stake: int = 100,
    max_players: int | None = None,  # IGNORED — kept for back-compat; server derives from target
    min_players: int | None = None,  # IGNORED — server derives from target via MIN_SEATED_BY_TARGET
    bot_count: int = 0,              # 2026-05: dev-only, validated by router
) -> Dict[str, Any]:
    if not _TABLE_NAME_RE.match(name or ""):
        raise LobbyError("INVALID_TABLE_NAME", "letters/digits/space/_/-, 2–32 chars")
    if target_score not in VALID_TARGET_SCORES:
        raise LobbyError(
            "INVALID_TARGET_SCORE",
            f"must be one of {sorted(VALID_TARGET_SCORES)}",
        )
    # Per GAME_RULES_LOCKED.md §2: seats AND min-seated-to-start are a
    # function of target_score. Any client-supplied max_players /
    # min_players is silently ignored to avoid breaking older clients
    # during the migration window.
    #   - 4-seat tables (target 30/50): start when seated ≥ 2.
    #   - 5-seat tables (target 75/100): start when seated ≥ 3.
    # There is NO 2-seat table type; "n_players=2" in tests means a
    # 4-seat table partially filled.
    derived_max = seats_for_target(target_score)
    derived_min = min_seated_for_target(target_score)
    if stake < 0 or stake > 1_000_000:
        raise LobbyError("INVALID_STAKE")

    creator = await get_user(db, creator_user_id)
    if not creator:
        raise LobbyError("UNKNOWN_USER")

    table_id = f"tbl_{uuid.uuid4().hex[:12]}"
    doc = {
        "table_id": table_id,
        "name": name,
        "creator_user_id": creator_user_id,
        "target_score": target_score,
        "stake": stake,
        "max_players": derived_max,
        "min_players": derived_min,
        "bot_count": int(bot_count),
        "status": "LOBBY",
        "seats": [{
            "user_id": creator_user_id,
            "username": creator["username"],
            "joined_at": _now(),
        }],
        "created_at": _now(),
        "started_at": None,
    }
    await db["lobby_tables"].insert_one(dict(doc))
    return _public_table(doc)


async def list_tables(db: AsyncIOMotorDatabase, status: str = "LOBBY") -> List[Dict[str, Any]]:
    cursor = db["lobby_tables"].find({"status": status}, {"_id": 0}).sort("created_at", -1)
    return [_public_table(d) async for d in cursor]


async def get_table(db: AsyncIOMotorDatabase, table_id: str) -> Optional[Dict[str, Any]]:
    doc = await db["lobby_tables"].find_one({"table_id": table_id}, {"_id": 0})
    return _public_table(doc) if doc else None


async def join_table(
    db: AsyncIOMotorDatabase, *, table_id: str, user_id: str,
) -> Dict[str, Any]:
    user = await get_user(db, user_id)
    if not user:
        raise LobbyError("UNKNOWN_USER")
    doc = await db["lobby_tables"].find_one({"table_id": table_id}, {"_id": 0})
    if not doc:
        raise LobbyError("TABLE_NOT_FOUND")
    if doc["status"] != "LOBBY":
        raise LobbyError("TABLE_NOT_JOINABLE")
    seats = list(doc.get("seats", []))
    if any(s["user_id"] == user_id for s in seats):
        return _public_table(doc)
    if len(seats) >= int(doc["max_players"]):
        raise LobbyError("TABLE_FULL")
    new_seat = {"user_id": user_id, "username": user["username"], "joined_at": _now()}
    upd = await db["lobby_tables"].find_one_and_update(
        {"table_id": table_id, "status": "LOBBY", f"seats.{int(doc['max_players']) - 1}": {"$exists": False}},
        {"$push": {"seats": new_seat}},
        return_document=True,
        projection={"_id": 0},
    )
    if not upd:
        raise LobbyError("TABLE_FULL")
    return _public_table(upd)


async def leave_table(
    db: AsyncIOMotorDatabase, *, table_id: str, user_id: str,
) -> Dict[str, Any]:
    doc = await db["lobby_tables"].find_one({"table_id": table_id}, {"_id": 0})
    if not doc:
        raise LobbyError("TABLE_NOT_FOUND")
    if doc["status"] != "LOBBY":
        raise LobbyError("TABLE_ALREADY_STARTED")
    new_seats = [s for s in doc.get("seats", []) if s["user_id"] != user_id]
    if len(new_seats) == 0:
        # Last player left — delete the table outright.
        await db["lobby_tables"].delete_one({"table_id": table_id})
        return {"deleted": True, "table_id": table_id}
    await db["lobby_tables"].update_one(
        {"table_id": table_id},
        {"$set": {"seats": new_seats}},
    )
    doc["seats"] = new_seats
    return _public_table(doc)


async def mark_table_running(
    db: AsyncIOMotorDatabase, table_id: str,
) -> Dict[str, Any]:
    upd = await db["lobby_tables"].find_one_and_update(
        {"table_id": table_id, "status": "LOBBY"},
        {"$set": {"status": "RUNNING", "started_at": _now()}},
        return_document=True,
        projection={"_id": 0},
    )
    if not upd:
        raise LobbyError("TABLE_NOT_STARTABLE")
    return _public_table(upd)
