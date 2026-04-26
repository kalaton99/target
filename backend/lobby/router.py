"""Phase 11 P2 — Lobby HTTP router.

Routes (all under /api/v2/lobby):

  POST /auth                           guest register-or-login by username
  GET  /me                             return current user (auth required)
  GET  /tables                         list LOBBY tables (public)
  POST /tables                         create a table (auth)  — auto-joins
  GET  /tables/{id}                    table detail (public)
  POST /tables/{id}/join               join (auth)
  POST /tables/{id}/leave              leave (auth)
  POST /tables/{id}/start              creator-only; spawns engine + bot if alone
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core import db as core_db
from core.security import create_token, current_user_id
from core.constants import DEFAULT_TARGET_SCORE
from game_engine.turn_engine import TurnEngine
from game_engine.types import GameState, PlayerState
from realtime_v2.bridge import EngineBridge

from . import service

logger = logging.getLogger("lobby.router")


# ---------- request / response shapes ----------

class AuthRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=16)


class CreateTableRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=32)
    target_score: int = Field(default=DEFAULT_TARGET_SCORE)
    stake: int = Field(default=100, ge=0, le=1_000_000)
    max_players: int = Field(default=2, ge=2, le=8)
    min_players: int = Field(default=2, ge=2, le=8)


# ---------- helper: spawn engine + start hand ----------

async def _spawn_engine_for_table(
    bridge: EngineBridge,
    table_doc: Dict[str, Any],
    *,
    spawn_bot_if_alone: bool = True,
) -> Dict[str, Any]:
    """Create a TurnEngine for a started table, register it in the bridge,
    and START_HAND. Returns the table_doc unchanged (with engine running).
    """
    from realtime_v2.dev_router import _BotDriver  # lazy import to avoid cycles

    table_id = table_doc["table_id"]
    if bridge.has_engine(table_id):
        return table_doc

    seats = list(table_doc.get("seats", []))
    bot_user_id: Optional[str] = None
    bot_username: Optional[str] = None
    if len(seats) < table_doc["min_players"] and spawn_bot_if_alone:
        # Pad the seats with a single bot to reach min_players (MVP: 1 bot).
        suffix = uuid.uuid4().hex[:6]
        bot_user_id = f"u_bot_{suffix}"
        bot_username = f"Bot_{suffix}"
        seats.append({
            "user_id": bot_user_id,
            "username": bot_username,
            "joined_at": None,
        })

    state = GameState(
        table_id=table_id,
        target_score=int(table_doc["target_score"]),
        stake=int(table_doc["stake"]),
        max_players=int(table_doc["max_players"]),
    )
    state.players = [
        PlayerState(
            seat_index=i,
            user_id=s["user_id"],
            username=s["username"],
            balance_at_start=10000,  # MVP: every seat starts with 10k credits
        )
        for i, s in enumerate(seats)
    ]
    engine = TurnEngine(state, turn_timeout_ms=15000)
    bridge.register_engine(table_id, engine)
    await engine.start()

    if bot_user_id is not None:
        # Find the bot's seat to drive it.
        bot_seat = next(
            i for i, s in enumerate(seats) if s["user_id"] == bot_user_id
        )
        bot = _BotDriver(bridge, table_id, bot_user_id, bot_seat=bot_seat)
        await bot.start()

    await engine.submit({
        "type": "START_HAND",
        "source": "SERVER",
        "hand_id": f"h_{uuid.uuid4().hex[:10]}",
        "nonce": 0,
        "server_seed": "0" * 64,
        "server_seed_hash": "h" * 64,
        "client_seeds": "",
        "target_score": int(table_doc["target_score"]),
    })
    return table_doc


# ---------- factory ----------

def build_lobby_router(bridge: EngineBridge) -> APIRouter:
    router = APIRouter(prefix="/v2/lobby", tags=["lobby"])

    def _err(exc: service.LobbyError) -> HTTPException:
        return HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})

    @router.post("/auth")
    async def auth(body: AuthRequest):
        try:
            user = await service.upsert_guest_user(core_db.db, body.username)
        except service.LobbyError as e:
            raise _err(e)
        token = create_token(user["user_id"])
        return {"user_id": user["user_id"], "username": user["username"], "token": token}

    @router.get("/me")
    async def me(user_id: str = Depends(current_user_id)):
        user = await service.get_user(core_db.db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="USER_NOT_FOUND")
        return user

    @router.get("/tables")
    async def list_tables() -> List[Dict[str, Any]]:
        return await service.list_tables(core_db.db, status="LOBBY")

    @router.post("/tables", status_code=status.HTTP_201_CREATED)
    async def create_table(body: CreateTableRequest, user_id: str = Depends(current_user_id)):
        try:
            return await service.create_table(
                core_db.db,
                creator_user_id=user_id,
                name=body.name,
                target_score=body.target_score,
                stake=body.stake,
                max_players=body.max_players,
                min_players=body.min_players,
            )
        except service.LobbyError as e:
            raise _err(e)

    @router.get("/tables/{table_id}")
    async def get_table(table_id: str):
        t = await service.get_table(core_db.db, table_id)
        if not t:
            raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
        return t

    @router.post("/tables/{table_id}/join")
    async def join_table(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            return await service.join_table(core_db.db, table_id=table_id, user_id=user_id)
        except service.LobbyError as e:
            raise _err(e)

    @router.post("/tables/{table_id}/leave")
    async def leave_table(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            return await service.leave_table(core_db.db, table_id=table_id, user_id=user_id)
        except service.LobbyError as e:
            raise _err(e)

    @router.post("/tables/{table_id}/start")
    async def start_table(table_id: str, user_id: str = Depends(current_user_id)):
        t = await service.get_table(core_db.db, table_id)
        if not t:
            raise HTTPException(status_code=404, detail="TABLE_NOT_FOUND")
        if t["creator_user_id"] != user_id:
            raise HTTPException(status_code=403, detail="ONLY_CREATOR_CAN_START")
        if t["status"] != "LOBBY":
            raise HTTPException(status_code=400, detail="TABLE_NOT_STARTABLE")
        # Mark RUNNING first to lock joins, then spawn engine.
        try:
            t = await service.mark_table_running(core_db.db, table_id)
        except service.LobbyError as e:
            raise _err(e)
        await _spawn_engine_for_table(bridge, t, spawn_bot_if_alone=True)
        return t

    return router
