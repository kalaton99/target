from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from core import db as core_db
from core.security import current_user_id
from target.wallet_bridge import build_ledger_from_db

from .service import TmargetError, TmargetService


class MarketCreateRequest(BaseModel):
    title: str
    description: str = ""
    category: str = "General"
    close_time: str
    resolution_criteria: str
    source_url: str = ""
    invalid_conditions: str = ""
    timezone: str = "UTC"
    initial_liquidity: int = Field(default=100, gt=0)
    outcome_type: str = "binary"


class MarketUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    close_time: Optional[str] = None
    resolution_criteria: Optional[str] = None
    source_url: Optional[str] = None


class TradeRequest(BaseModel):
    outcome: str
    shares: int = Field(gt=0)


class ResolveRequest(BaseModel):
    outcome: str
    resolver_notes: str


def build_tmarget_router(service: TmargetService | None = None) -> APIRouter:
    router = APIRouter(prefix="/tmarget", tags=["tmarget"])
    svc = service or TmargetService()

    def _ledger():
        return build_ledger_from_db(core_db.db, audit_col=core_db.db["audit_log"])

    def _err(exc: TmargetError) -> HTTPException:
        return HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message})

    async def demo_admin_guard(x_demo_admin: str = Header(default="1")):
        enabled = os.environ.get("TMARGET_DEMO_ADMIN_ENABLED", "1").lower() not in {"0", "false", "no"}
        if not enabled or x_demo_admin not in {"1", "true", "demo"}:
            raise HTTPException(status_code=403, detail="TMARGET_DEMO_ADMIN_ONLY")

    @router.get("/markets")
    async def list_markets():
        return {"markets": svc.list_markets()}

    @router.get("/markets/{market_id_or_slug}")
    async def get_market(market_id_or_slug: str):
        try:
            return svc.market_payload(svc.get_market(market_id_or_slug))
        except TmargetError as exc:
            raise _err(exc)

    @router.get("/markets/{market_id}/trades")
    async def trades(market_id: str):
        try:
            market = svc.get_market(market_id)
            return {"trades": svc.market_trades(market.id)}
        except TmargetError as exc:
            raise _err(exc)

    @router.get("/markets/{market_id}/positions")
    async def market_positions(market_id: str, user_id: str = Depends(current_user_id)):
        try:
            market = svc.get_market(market_id)
            return {"positions": svc.market_positions(market.id, user_id)}
        except TmargetError as exc:
            raise _err(exc)

    @router.get("/me/positions")
    async def me_positions(user_id: str = Depends(current_user_id)):
        return {"positions": svc.user_positions(user_id)}

    @router.post("/markets/{market_id}/buy")
    async def buy(market_id: str, body: TradeRequest, user_id: str = Depends(current_user_id)):
        try:
            trade = await svc.buy(
                market_id=market_id,
                user_id=user_id,
                outcome=body.outcome,
                shares=body.shares,
                ledger=_ledger(),
            )
            return {"trade": trade.to_dict(), "market": svc.market_payload(svc.get_market(market_id))}
        except TmargetError as exc:
            raise _err(exc)

    @router.post("/markets/{market_id}/sell")
    async def sell(market_id: str, body: TradeRequest, user_id: str = Depends(current_user_id)):
        try:
            trade = await svc.sell(
                market_id=market_id,
                user_id=user_id,
                outcome=body.outcome,
                shares=body.shares,
                ledger=_ledger(),
            )
            return {"trade": trade.to_dict(), "market": svc.market_payload(svc.get_market(market_id))}
        except TmargetError as exc:
            raise _err(exc)

    @router.post("/admin/markets", dependencies=[Depends(demo_admin_guard)])
    async def create_market(body: MarketCreateRequest, user_id: str = Depends(current_user_id)):
        try:
            market = svc.create_market(created_by=user_id, **body.dict())
            return svc.market_payload(market)
        except TmargetError as exc:
            raise _err(exc)

    @router.patch("/admin/markets/{market_id}", dependencies=[Depends(demo_admin_guard)])
    async def update_market(market_id: str, body: MarketUpdateRequest):
        try:
            return svc.market_payload(svc.update_market(market_id, **body.dict(exclude_unset=True)))
        except TmargetError as exc:
            raise _err(exc)

    @router.post("/admin/markets/{market_id}/open", dependencies=[Depends(demo_admin_guard)])
    async def open_market(market_id: str):
        try:
            return svc.market_payload(svc.open_market(market_id))
        except TmargetError as exc:
            raise _err(exc)

    @router.post("/admin/markets/{market_id}/pause", dependencies=[Depends(demo_admin_guard)])
    async def pause_market(market_id: str):
        try:
            return svc.market_payload(svc.pause_market(market_id))
        except TmargetError as exc:
            raise _err(exc)

    @router.post("/admin/markets/{market_id}/close", dependencies=[Depends(demo_admin_guard)])
    async def close_market(market_id: str):
        try:
            return svc.market_payload(svc.close_market(market_id))
        except TmargetError as exc:
            raise _err(exc)

    @router.post("/admin/markets/{market_id}/resolve", dependencies=[Depends(demo_admin_guard)])
    async def resolve_market(market_id: str, body: ResolveRequest):
        try:
            return svc.market_payload(await svc.resolve_market(
                market_id=market_id,
                outcome=body.outcome,
                resolver_notes=body.resolver_notes,
                ledger=_ledger(),
            ))
        except TmargetError as exc:
            raise _err(exc)

    @router.post("/admin/markets/{market_id}/cancel", dependencies=[Depends(demo_admin_guard)])
    async def cancel_market(market_id: str):
        try:
            return svc.market_payload(await svc.cancel_market(market_id, _ledger()))
        except TmargetError as exc:
            raise _err(exc)

    return router
