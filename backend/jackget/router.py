from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.security import current_user_id

from .models import JACKGET_MAX_PLAYERS, JACKGET_MIN_PLAYERS
from .service import JackgetError, JackgetService


class CreateJackgetTableRequest(BaseModel):
    max_players: int = Field(default=JACKGET_MAX_PLAYERS, ge=JACKGET_MIN_PLAYERS, le=JACKGET_MAX_PLAYERS)


class SpinRequest(BaseModel):
    reels: list[str] | None = None


def build_jackget_router(service: JackgetService | None = None) -> APIRouter:
    router = APIRouter(prefix="/jackget", tags=["jackget"])
    svc = service or JackgetService()

    def _err(exc: JackgetError) -> HTTPException:
        return HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})

    @router.post("/tables", status_code=status.HTTP_201_CREATED)
    async def create_table(body: CreateJackgetTableRequest, user_id: str = Depends(current_user_id)):
        try:
            return svc.create_table(
                creator_user_id=user_id,
                username=user_id,
                max_players=body.max_players,
            ).to_dict()
        except JackgetError as exc:
            raise _err(exc)

    @router.get("/tables")
    async def list_tables():
        return svc.list_tables()

    @router.get("/tables/{table_id}")
    async def get_table(table_id: str):
        try:
            return svc.get_table(table_id).to_dict()
        except JackgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/join")
    async def join_table(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            return svc.join_table(table_id=table_id, user_id=user_id, username=user_id).to_dict()
        except JackgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/add-demo-opponents")
    async def add_demo_opponents(table_id: str):
        try:
            return svc.add_demo_opponents(table_id=table_id).to_dict()
        except JackgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/start")
    async def start(table_id: str, user_id: str = Depends(current_user_id)):
        try:
            return svc.start_table(table_id=table_id, user_id=user_id).to_dict()
        except JackgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/spin")
    async def spin(table_id: str, body: SpinRequest | None = None, user_id: str = Depends(current_user_id)):
        try:
            return svc.spin(table_id=table_id, user_id=user_id, reels=(body.reels if body else None)).to_dict()
        except JackgetError as exc:
            raise _err(exc)

    @router.post("/tables/{table_id}/auto-play-demo-spins")
    async def auto_play_demo_spins(table_id: str):
        try:
            return svc.auto_play_demo_spins(table_id=table_id).to_dict()
        except JackgetError as exc:
            raise _err(exc)

    return router
