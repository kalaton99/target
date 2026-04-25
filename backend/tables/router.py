"""Table REST endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from . import service
from core.security import current_user_id

router = APIRouter(prefix="/tables", tags=["tables"])


class CreateTableRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    type: str = "FREE"
    stake: int = 100
    max_players: int = 4


class QuickJoinRequest(BaseModel):
    type: str = "FREE"


@router.get("")
async def list_tables(user_id: str = Depends(current_user_id)):
    return {"tables": await service.list_tables()}


@router.post("")
async def create_table(req: CreateTableRequest, user_id: str = Depends(current_user_id)):
    return await service.create_table(user_id, req.name, req.type, req.stake, req.max_players)


@router.get("/{table_id}")
async def get_table(table_id: str, user_id: str = Depends(current_user_id)):
    return await service.get_table(table_id)


@router.post("/{table_id}/join")
async def join(table_id: str, user_id: str = Depends(current_user_id)):
    return await service.join_table(user_id, table_id)


@router.post("/quick-join")
async def quick_join(req: QuickJoinRequest, user_id: str = Depends(current_user_id)):
    return await service.quick_join(user_id, req.type)


@router.post("/{table_id}/leave")
async def leave(table_id: str, user_id: str = Depends(current_user_id)):
    return await service.leave_table(user_id, table_id)
