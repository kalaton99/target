"""Table service: create, list, quick-join."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from core import db
from core.constants import (
    MIN_PLAYERS,
    MAX_PLAYERS,
    COMMISSION_FREE_BPS,
    COMMISSION_PAID_BPS,
    LOTTERY_BPS,
    TARGET_SCORE,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_table(
    user_id: str,
    name: str,
    table_type: str = "FREE",
    stake: int = 100,
    max_players: int = 4,
) -> Dict[str, Any]:
    if table_type not in ("FREE", "PAID"):
        raise HTTPException(400, "INVALID_TABLE_TYPE")
    if not (MIN_PLAYERS <= max_players <= MAX_PLAYERS):
        raise HTTPException(400, "INVALID_MAX_PLAYERS")
    if stake < 10:
        raise HTTPException(400, "INVALID_STAKE")
    table_id = f"t_{uuid.uuid4().hex[:20]}"
    seats = [
        {"seat_index": i, "user_id": None, "joined_at": None, "sitting_out": False}
        for i in range(max_players)
    ]
    doc = {
        "id": table_id,
        "name": name,
        "type": table_type,
        "stake": stake,
        "entry_fee": 0,
        "max_players": max_players,
        "target_score": TARGET_SCORE,
        "turn_timer_seconds": 15,
        "status": "OPEN",
        "seats": seats,
        "current_hand_id": None,
        "created_at": _now_iso(),
        "created_by": user_id,
        "commission_rate_bps": COMMISSION_PAID_BPS if table_type == "PAID" else COMMISSION_FREE_BPS,
        "lottery_rate_bps": LOTTERY_BPS,
    }
    await db.tables.insert_one(doc)
    return await get_table(table_id)


async def list_tables() -> List[Dict[str, Any]]:
    cursor = db.tables.find({"status": {"$in": ["OPEN", "IN_HAND"]}}, {"_id": 0}).sort("created_at", -1).limit(50)
    return [doc async for doc in cursor]


async def get_table(table_id: str) -> Dict[str, Any]:
    table = await db.tables.find_one({"id": table_id}, {"_id": 0})
    if not table:
        raise HTTPException(404, "TABLE_NOT_FOUND")
    return table


async def join_table(user_id: str, table_id: str) -> Dict[str, Any]:
    table = await db.tables.find_one({"id": table_id}, {"_id": 0})
    if not table:
        raise HTTPException(404, "TABLE_NOT_FOUND")
    # Already seated?
    for s in table["seats"]:
        if s["user_id"] == user_id:
            return {"table_id": table_id, "seat_index": s["seat_index"]}
    # Find first empty
    for s in table["seats"]:
        if s["user_id"] is None:
            # Atomic claim using array filter
            res = await db.tables.update_one(
                {"id": table_id, "seats.seat_index": s["seat_index"], "seats.user_id": None},
                {
                    "$set": {
                        "seats.$.user_id": user_id,
                        "seats.$.joined_at": _now_iso(),
                    }
                },
            )
            if res.modified_count == 1:
                return {"table_id": table_id, "seat_index": s["seat_index"]}
    raise HTTPException(409, "TABLE_FULL")


async def quick_join(
    user_id: str,
    table_type: str = "FREE",
) -> Dict[str, Any]:
    """Find an open table with a free seat or create a new one."""
    cursor = db.tables.find(
        {"status": "OPEN", "type": table_type, "seats.user_id": None},
        {"_id": 0},
    ).limit(20)
    candidates = [doc async for doc in cursor]
    for t in candidates:
        try:
            return await join_table(user_id, t["id"])
        except HTTPException:
            continue
    # None found -> create
    new_table = await create_table(user_id, "Quick Match", table_type=table_type, stake=100, max_players=4)
    return await join_table(user_id, new_table["id"])


async def leave_table(user_id: str, table_id: str) -> Dict[str, Any]:
    res = await db.tables.update_one(
        {"id": table_id, "seats.user_id": user_id},
        {
            "$set": {
                "seats.$.user_id": None,
                "seats.$.joined_at": None,
                "seats.$.sitting_out": False,
            }
        },
    )
    return {"left": res.modified_count == 1}
