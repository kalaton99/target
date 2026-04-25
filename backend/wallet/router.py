"""Wallet REST endpoints."""
from fastapi import APIRouter, Depends, HTTPException

from . import service
from core.security import current_user_id

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("/balance")
async def balance(user_id: str = Depends(current_user_id)):
    wallet = await service.get_wallet(user_id)
    if not wallet:
        raise HTTPException(404, "WALLET_NOT_FOUND")
    return {
        "balance": wallet["balance"],
        "gems": wallet.get("gems", 0),
        "version": wallet["version"],
    }


@router.get("/transactions")
async def transactions(user_id: str = Depends(current_user_id), limit: int = 50):
    return {"transactions": await service.list_transactions(user_id, limit)}
