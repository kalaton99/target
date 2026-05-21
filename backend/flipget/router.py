from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core import db as core_db
from core.config import SIGNUP_BONUS
from core.security import current_user_id

from .models import FLIPGET_SEATS
from .service import FlipgetError, FlipgetService
from .wallet_bridge import (
    FlipgetWalletError,
    build_ledger_from_db,
    lock_flipget_stake,
    unlock_flipget_stake,
)


class CreateFlipgetTableRequest(BaseModel):
    stake_amount: int = Field(default=100, ge=0, le=1_000_000)
    max_players: int = FLIPGET_SEATS
    mode: str = Field(default="single_flip")


class SideRequest(BaseModel):
    side: str


class DemoOpponentRequest(BaseModel):
    username: str = "Demo Opponent"


def build_flipget_router(service: FlipgetService | None = None) -> APIRouter:
    router = APIRouter(prefix="/flipget", tags=["flipget"])
    svc = service or FlipgetService()

    def _ledger():
        return build_ledger_from_db(core_db.db, audit_col=core_db.db["audit_log"])

    def _err(exc: FlipgetError) -> HTTPException:
        return HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})

    def _wallet_err(exc: FlipgetWalletError) -> HTTPException:
        return HTTPException(status_code=402, detail={"code": exc.__class__.__name__, "message": str(exc)})

    def _is_demo_opponent(user_id: str) -> bool:
        return user_id.startswith("fg_demo_opponent_")

    def _opposite_side(side: str) -> str:
        return "tails" if side == "heads" else "heads"

    def _ready_existing_demo_opponent_for_round(table_id: str, caller_user_id: str):
        table = svc.get_table(table_id)
        caller = next((seat for seat in table.seats if seat.user_id == caller_user_id), None)
        demo = next((seat for seat in table.seats if _is_demo_opponent(seat.user_id)), None)
        if (
            caller is None
            or demo is None
            or _is_demo_opponent(caller.user_id)
            or caller.side not in {"heads", "tails"}
            or table.status in {"flipping", "settled"}
        ):
            return table
        if demo.side is None:
            table = svc.choose_side(table_id=table_id, user_id=demo.user_id, side=_opposite_side(caller.side))
            demo = next((seat for seat in table.seats if _is_demo_opponent(seat.user_id)), None)
        if demo is not None and not demo.ready:
            table = svc.ready(table_id=table_id, user_id=demo.user_id)
        return table

    @router.post("/tables", status_code=status.HTTP_201_CREATED)
    async def create_table(body: CreateFlipgetTableRequest, user_id: str = Depends(current_user_id)):
        try:
            await _ledger().open_wallet(user_id, opening_balance=SIGNUP_BONUS)
            table = svc.create_table(
                creator_user_id=user_id,
                username=user_id,
                stake_amount=body.stake_amount,
                max_players=body.max_players,
                mode=body.mode,
            )
            try:
                await lock_flipget_stake(
                    _ledger(),
                    table_id=table.id,
                    user_id=user_id,
                    stake=table.stake_amount,
                )
            except FlipgetWalletError as exc:
                svc.tables.pop(table.id, None)
                raise _wallet_err(exc)
            return table.to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    @router.get("/tables")
    async def list_tables():
        return svc.list_tables()

    @router.get("/tables/{table_id}")
    async def get_table(table_id: str):
        try:
            return svc.get_table(table_id).to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/join")
    async def join_table(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            table = svc.join_table(table_id=table_id, user_id=user_id, username=user_id)
            try:
                await _ledger().open_wallet(user_id, opening_balance=SIGNUP_BONUS)
                await lock_flipget_stake(
                    _ledger(),
                    table_id=table.id,
                    user_id=user_id,
                    stake=table.stake_amount,
                )
            except FlipgetWalletError as exc:
                svc.leave_table(table_id=table_id, user_id=user_id)
                raise _wallet_err(exc)
            return table.to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/choose-side")
    async def choose_side(table_id: str, body: SideRequest, user_id: str = Depends(current_user_id)):
        try:
            svc.choose_side(table_id=table_id, user_id=user_id, side=body.side)
            return _ready_existing_demo_opponent_for_round(table_id, user_id).to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/ready")
    async def ready(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            return svc.ready(table_id=table_id, user_id=user_id).to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/add-demo-opponent")
    async def add_demo_opponent(
        table_id: str,
        body: DemoOpponentRequest | None = None,
        user_id: str = Depends(current_user_id),
    ):
        try:
            table = svc.get_table(table_id)
            caller = next((seat for seat in table.seats if seat.user_id == user_id), None)
            if caller is None:
                raise FlipgetError("PLAYER_NOT_SEATED")
            if caller.side not in {"heads", "tails"}:
                raise FlipgetError("SIDE_REQUIRED")
            if len(table.seats) >= FLIPGET_SEATS:
                raise FlipgetError("TABLE_FULL", "Flipget already has two participants")
            opponent_side = "tails" if caller.side == "heads" else "heads"
            opponent_id = f"fg_demo_opponent_{table_id[-8:]}"
            table = svc.join_table(
                table_id=table_id,
                user_id=opponent_id,
                username=(body.username if body else "Demo Opponent"),
            )
            try:
                await _ledger().open_wallet(opponent_id, opening_balance=SIGNUP_BONUS)
                await lock_flipget_stake(
                    _ledger(),
                    table_id=table.id,
                    user_id=opponent_id,
                    stake=table.stake_amount,
                )
            except FlipgetWalletError as exc:
                svc.leave_table(table_id=table_id, user_id=opponent_id)
                raise _wallet_err(exc)
            table = svc.choose_side(table_id=table_id, user_id=opponent_id, side=opponent_side)
            table = svc.ready(table_id=table_id, user_id=opponent_id)
            return table.to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/flip")
    async def flip(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            return (await svc.flip(table_id=table_id, user_id=user_id, ledger=_ledger())).to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/leave")
    async def leave(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            table = svc.get_table(table_id)
            try:
                await unlock_flipget_stake(
                    _ledger(),
                    table_id=table.id,
                    user_id=user_id,
                    stake=table.stake_amount,
                    table_status=table.status,
                )
            except FlipgetWalletError as exc:
                raise _wallet_err(exc)
            result = svc.leave_table(table_id=table_id, user_id=user_id)
            return result if isinstance(result, dict) else result.to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/deal-again")
    async def deal_again(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            table = svc.deal_again(table_id=table_id, user_id=user_id)
            await lock_flipget_stake(
                _ledger(),
                table_id=table.id,
                user_id=user_id,
                stake=table.stake_amount,
            )
            return table.to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    return router
