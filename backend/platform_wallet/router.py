from __future__ import annotations

from fastapi import APIRouter, Depends

from core import db as core_db
from core.security import current_user_id

from .service import get_wallet_summary, list_ledger_entries


router = APIRouter(prefix="/platform", tags=["platform-wallet"])


@router.get("/wallet/me")
async def wallet_me(user_id: str = Depends(current_user_id)):
    return await get_wallet_summary(core_db.db, user_id)


@router.get("/ledger/me")
async def ledger_me(user_id: str = Depends(current_user_id), limit: int = 100):
    return {"entries": await list_ledger_entries(core_db.db, user_id, limit=limit)}
