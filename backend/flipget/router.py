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


class SideRequest(BaseModel):
    side: str


def build_flipget_router(service: FlipgetService | None = None) -> APIRouter:
    router = APIRouter(prefix="/flipget", tags=["flipget"])
    svc = service or FlipgetService()

    def _ledger():
        return build_ledger_from_db(core_db.db, audit_col=core_db.db["audit_log"])

    def _err(exc: FlipgetError) -> HTTPException:
        return HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})

    def _wallet_err(exc: FlipgetWalletError) -> HTTPException:
        return HTTPException(status_code=402, detail={"code": exc.__class__.__name__, "message": str(exc)})

    @router.post("/tables", status_code=status.HTTP_201_CREATED)
    async def create_table(body: CreateFlipgetTableRequest, user_id: str = Depends(current_user_id)):
        try:
            await _ledger().open_wallet(user_id, opening_balance=SIGNUP_BONUS)
            table = svc.create_table(
                creator_user_id=user_id,
                username=user_id,
                stake_amount=body.stake_amount,
                max_players=body.max_players,
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
            return svc.choose_side(table_id=table_id, user_id=user_id, side=body.side).to_dict()
        except FlipgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/ready")
    async def ready(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            return svc.ready(table_id=table_id, user_id=user_id).to_dict()
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
