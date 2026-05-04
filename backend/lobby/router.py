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
from core.constants import (
    ALLOW_BOTS,
    BOT_COUNT_MAX,
    DEFAULT_TARGET_SCORE,
    TABLE_SEATS_BY_TARGET,
    max_bots_for_target,
)
from game_engine.rng import generate_server_seed
from game_engine.turn_engine import TurnEngine
from game_engine.types import GameState, PlayerState
from realtime_v2.bridge import EngineBridge

from . import service

logger = logging.getLogger("lobby.router")


# ---------- request / response shapes ----------

class AuthRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=16)


class CreateTableRequest(BaseModel):
    """Create-table payload.

    `max_players` / `min_players` are accepted but **ignored** — the
    server derives the seat count from `target_score` per
    GAME_RULES_LOCKED.md §2. Older clients still send them; we silently
    drop their values to avoid a hard-break. Future deploys may delete
    these fields entirely.

    `bot_count` is dev-only (clamped to 0..max_bots_for_target(target)).
    When ALLOW_BOTS is False (production default), any positive value
    is rejected with 400. The Pydantic `le=4` cap is a hard global
    ceiling; the per-target cap (`seats - 1`) is enforced by the route
    handler since it depends on the target_score in the same payload.
    """
    name: str = Field(..., min_length=2, max_length=32)
    target_score: int = Field(default=DEFAULT_TARGET_SCORE)
    stake: int = Field(default=100, ge=0, le=1_000_000)
    max_players: Optional[int] = Field(default=None)  # IGNORED (server-derived)
    min_players: Optional[int] = Field(default=None)  # IGNORED (server-derived)
    bot_count: int = Field(default=0, ge=0, le=4)


# ---------- helper: spawn engine + start hand ----------

async def _spawn_engine_for_table(
    bridge: EngineBridge,
    table_doc: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a TurnEngine for a started table, register it in the bridge,
    and START_HAND. Returns the table_doc unchanged (with engine running).

    Bot seating policy (2026-05, GAME_RULES_LOCKED.md §5):
      - If `ALLOW_BOTS` is False, no bots are added under any circumstance.
      - Otherwise, `bot_count` (clamped at table-creation to 0..BOT_COUNT_MAX)
        determines how many `u_bot_*` seats are appended, capped by the
        derived `max_players`.

    Older Phase-11-MVP "auto-spawn 1 bot if alone" behaviour is gone.
    Solo testing is now an explicit `bot_count >= 1` decision at table
    create time.
    """
    from realtime_v2.dev_router import _BotDriver  # lazy import to avoid cycles

    table_id = table_doc["table_id"]
    if bridge.has_engine(table_id):
        return table_doc

    seats = list(table_doc.get("seats", []))
    max_players = int(table_doc["max_players"])
    bots_seated: List[Dict[str, str]] = []
    if ALLOW_BOTS:
        requested = int(table_doc.get("bot_count", 0))
        # Clamp by free seats AND BOT_COUNT_MAX so we never exceed
        # max_players or the env-imposed cap.
        bots_to_add = max(0, min(requested, BOT_COUNT_MAX, max_players - len(seats)))
        for _ in range(bots_to_add):
            suffix = uuid.uuid4().hex[:6]
            bot_user_id = f"u_bot_{suffix}"
            bot_username = f"Bot_{suffix}"
            seat_doc = {
                "user_id": bot_user_id,
                "username": bot_username,
                "joined_at": None,
            }
            seats.append(seat_doc)
            bots_seated.append(seat_doc)

    state = GameState(
        table_id=table_id,
        target_score=int(table_doc["target_score"]),
        stake=int(table_doc["stake"]),
        max_players=max_players,
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

    # Drive each bot from its own _BotDriver task.
    for bot_seat_doc in bots_seated:
        bot_user_id = bot_seat_doc["user_id"]
        bot_seat = next(i for i, s in enumerate(seats) if s["user_id"] == bot_user_id)
        bot = _BotDriver(bridge, table_id, bot_user_id, bot_seat=bot_seat)
        await bot.start()

    # 2026-05 v2 — generate a real server_seed (commit-reveal RNG) and
    # record the commit hash. The plain seed is buffered inside the
    # engine state and revealed at SHOWDOWN. `nonce` uses the engine's
    # current hand_number+1 so subsequent hands at the same table get
    # distinct shuffles even with a fixed seed.
    plain_seed, seed_hash = generate_server_seed()
    await engine.submit({
        "type": "START_HAND",
        "source": "SERVER",
        "hand_id": f"h_{uuid.uuid4().hex[:10]}",
        "nonce": int(state.hand_number) + 1,
        "server_seed": plain_seed,
        "server_seed_hash": seed_hash,
        # Per-seat client seeds will be auto-collected from
        # `state.pending_client_seeds` (populated via SUBMIT_CLIENT_SEED).
        # No `client_seeds_by_seat` here so the reducer reads pending.
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

    @router.get("/config")
    async def config():
        """Public lobby/feature config. Used by the frontend to decide
        whether to render the (dev-only) bots input on the create-table
        form. Production deploys advertise `allow_bots=false` so the
        control is hidden.

        `bot_count_max_by_target` exposes the per-target bot ceiling
        (seats - 1), so the frontend can dynamically set the
        `<input max>` when the user changes the target select. A
        5-seat target-100 table allows 4 bots, a 4-seat target-30
        allows 3. When `allow_bots=false` every entry is 0.
        """
        per_target = (
            {t: max_bots_for_target(t) for t in TABLE_SEATS_BY_TARGET}
            if ALLOW_BOTS else
            {t: 0 for t in TABLE_SEATS_BY_TARGET}
        )
        return {
            "allow_bots": bool(ALLOW_BOTS),
            # Global ceiling (fallback for older clients that don't
            # consume the per-target map below).
            "bot_count_max": int(BOT_COUNT_MAX) if ALLOW_BOTS else 0,
            "bot_count_max_by_target": per_target,
            "table_seats_by_target": dict(TABLE_SEATS_BY_TARGET),
        }

    @router.get("/tables")
    async def list_tables() -> List[Dict[str, Any]]:
        return await service.list_tables(core_db.db, status="LOBBY")

    @router.post("/tables", status_code=status.HTTP_201_CREATED)
    async def create_table(body: CreateTableRequest, user_id: str = Depends(current_user_id)):
        # Validate bot request against the env-locked policy. Older
        # clients (or production deploys) MUST NOT be able to spawn bots
        # by sending bot_count > 0.
        if body.bot_count > 0:
            if not ALLOW_BOTS:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "BOTS_DISABLED",
                            "message": "bots are disabled on this server"},
                )
            # Per-target cap (seats - 1) — 5-seat target tables allow 4
            # bots, 4-seat allow 3. Global BOT_COUNT_MAX caps above that.
            per_target_cap = max_bots_for_target(body.target_score)
            if body.bot_count > per_target_cap:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "BOT_COUNT_EXCEEDED",
                        "message": (
                            f"target {body.target_score} allows at most "
                            f"{per_target_cap} bots"
                        ),
                        "bot_count_max": per_target_cap,
                    },
                )
        try:
            return await service.create_table(
                core_db.db,
                creator_user_id=user_id,
                name=body.name,
                target_score=body.target_score,
                stake=body.stake,
                bot_count=body.bot_count,
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
        await _spawn_engine_for_table(bridge, t)
        return t

    return router
