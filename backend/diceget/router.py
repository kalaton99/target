from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core import db as core_db
from core.config import SIGNUP_BONUS
from core.security import current_user_id

from .models import DICEGET_SEATS, BotProfile
from .service import DicegetError, DicegetService
from .wallet_bridge import (
    DicegetWalletError,
    build_ledger_from_db,
    lock_diceget_stake,
    unlock_diceget_stake,
)


class CreateDicegetTableRequest(BaseModel):
    target_score: int
    stake: int = Field(default=100, ge=0, le=1_000_000)
    max_players: int = DICEGET_SEATS


class AddBotRequest(BaseModel):
    profile: BotProfile = "normal"


def build_diceget_router(service: DicegetService | None = None) -> APIRouter:
    router = APIRouter(prefix="/diceget", tags=["diceget"])
    svc = service or DicegetService()

    def _ledger():
        return build_ledger_from_db(core_db.db, audit_col=core_db.db["audit_log"])

    def _err(exc: DicegetError) -> HTTPException:
        return HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})

    def _wallet_err(exc: DicegetWalletError) -> HTTPException:
        return HTTPException(status_code=402, detail={"code": exc.__class__.__name__, "message": str(exc)})

    @router.post("/tables", status_code=status.HTTP_201_CREATED)
    async def create_table(body: CreateDicegetTableRequest, user_id: str = Depends(current_user_id)):
        try:
            await _ledger().open_wallet(user_id, opening_balance=SIGNUP_BONUS)
            table = svc.create_table(
                creator_user_id=user_id,
                username=user_id,
                target_score=body.target_score,
                stake=body.stake,
                max_players=body.max_players,
            )
            try:
                await lock_diceget_stake(
                    _ledger(),
                    table_id=table.id,
                    user_id=user_id,
                    stake=table.stake,
                )
            except DicegetWalletError as exc:
                svc.tables.pop(table.id, None)
                raise _wallet_err(exc)
            return table.to_dict()
        except DicegetError as exc:
            raise _err(exc)

    @router.get("/tables")
    async def list_tables():
        return svc.list_tables()

    @router.get("/tables/{table_id}")
    async def get_table(table_id: str):
        try:
            return svc.get_table(table_id).to_dict()
        except DicegetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/join")
    async def join_table(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            table = svc.join_table(table_id=table_id, user_id=user_id, username=user_id)
            try:
                await _ledger().open_wallet(user_id, opening_balance=SIGNUP_BONUS)
                await lock_diceget_stake(
                    _ledger(),
                    table_id=table.id,
                    user_id=user_id,
                    stake=table.stake,
                )
            except DicegetWalletError as exc:
                svc.leave_table(table_id=table_id, user_id=user_id)
                raise _wallet_err(exc)
            return table.to_dict()
        except DicegetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/add-bot")
    async def add_bot(table_id: str, body: AddBotRequest):
        try:
            return svc.add_bot(table_id=table_id, profile=body.profile).to_dict()
        except DicegetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/start")
    async def start(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            return svc.start_table(table_id=table_id, user_id=user_id).to_dict()
        except DicegetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/roll")
    async def roll(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            return svc.roll(table_id=table_id, user_id=user_id).to_dict()
        except DicegetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/hold")
    async def hold(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            table = svc.hold(table_id=table_id, user_id=user_id)
            if table.status == "showdown":
                table = await svc.settle(table.id, _ledger())
            return table.to_dict()
        except DicegetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/forfeit")
    async def forfeit(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            table = svc.forfeit(table_id=table_id, user_id=user_id)
            if table.status == "showdown":
                table = await svc.settle(table.id, _ledger())
            return table.to_dict()
        except DicegetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/leave")
    async def leave(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            table = svc.get_table(table_id)
            try:
                await unlock_diceget_stake(
                    _ledger(),
                    table_id=table.id,
                    user_id=user_id,
                    stake=table.stake,
                    table_status=table.status,
                )
            except DicegetWalletError as exc:
                raise _wallet_err(exc)
            result = svc.leave_table(table_id=table_id, user_id=user_id)
            return result if isinstance(result, dict) else result.to_dict()
        except DicegetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/deal-again")
    async def deal_again(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            table = svc.deal_again(table_id=table_id, user_id=user_id)
            await lock_diceget_stake(
                _ledger(),
                table_id=table.id,
                user_id=user_id,
                stake=table.stake,
            )
            return table.to_dict()
        except DicegetError as exc:
            raise _err(exc)

    return router
