from __future__ import annotations

import re
import time
import uuid
from typing import Any, Optional

from ledger.service import InsufficientFunds, LedgerService, REASON_TMARKET_BUY_COST, REASON_TMARKET_SELL_CREDIT

from .models import (
    TmargetLiquidityPool,
    TmargetMarket,
    TmargetMarketRule,
    TmargetPosition,
    TmargetTrade,
)
from .pricing import estimate_trade, prices
from .repository import InMemoryTmargetRepository
from .settlement import credit_refund, credit_settlement, payout_amount


class TmargetError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _slug(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{base[:48]}-{uuid.uuid4().hex[:6]}"


class TmargetService:
    def __init__(self, repository: Optional[InMemoryTmargetRepository] = None):
        self.repo = repository or InMemoryTmargetRepository()

    @property
    def markets(self) -> dict[str, TmargetMarket]:
        return self.repo.markets

    @property
    def positions(self) -> dict[tuple[str, str, str], TmargetPosition]:
        return self.repo.positions

    @property
    def trades(self) -> list[TmargetTrade]:
        return self.repo.trades

    def list_markets(self) -> list[dict[str, Any]]:
        return [self.market_payload(market) for market in self.repo.list_markets()]

    def get_market(self, market_id_or_slug: str) -> TmargetMarket:
        market = self.repo.get_market(market_id_or_slug)
        if market is not None:
            return market
        raise TmargetError("MARKET_NOT_FOUND")

    def market_payload(self, market: TmargetMarket) -> dict[str, Any]:
        yes, no = prices(market.pool.yes_pool, market.pool.no_pool)
        data = market.to_dict()
        data["yes_price"] = yes
        data["no_price"] = no
        return data

    def create_market(
        self,
        *,
        title: str,
        description: str,
        category: str,
        close_time: str,
        resolution_criteria: str,
        source_url: str = "",
        invalid_conditions: str = "",
        timezone: str = "UTC",
        initial_liquidity: int = 100,
        created_by: str,
        outcome_type: str = "binary",
    ) -> TmargetMarket:
        if not title or not title.strip():
            raise TmargetError("TITLE_REQUIRED")
        if not resolution_criteria or not resolution_criteria.strip():
            raise TmargetError("RESOLUTION_CRITERIA_REQUIRED")
        if not close_time or "invalid" in close_time.lower():
            raise TmargetError("VALID_CLOSE_TIME_REQUIRED")
        if outcome_type != "binary":
            raise TmargetError("ONLY_BINARY_MARKETS_SUPPORTED")
        if initial_liquidity <= 0:
            raise TmargetError("INITIAL_LIQUIDITY_REQUIRED")
        market_id = _new_id("tm_mkt")
        now = _now()
        rule = TmargetMarketRule(
            market_id=market_id,
            source_url=source_url,
            resolution_criteria=resolution_criteria,
            invalid_conditions=invalid_conditions,
            timezone=timezone,
        )
        pool = TmargetLiquidityPool(
            market_id=market_id,
            yes_pool=float(initial_liquidity),
            no_pool=float(initial_liquidity),
            liquidity_parameter=float(initial_liquidity),
            updated_at=now,
        )
        market = TmargetMarket(
            id=market_id,
            slug=_slug(title),
            title=title.strip(),
            description=description.strip(),
            category=category.strip() or "General",
            status="draft",
            outcome_type="binary",
            yes_label="YES",
            no_label="NO",
            close_time=close_time,
            resolution_time=None,
            resolved_outcome=None,
            resolver_notes="",
            created_by=created_by,
            created_at=now,
            updated_at=now,
            rule=rule,
            pool=pool,
        )
        self.repo.create_market(market)
        self.repo.record_admin_action("create_market", market.id, created_by, {"title": market.title})
        return market

    def update_market(self, market_id: str, **fields: Any) -> TmargetMarket:
        market = self.get_market(market_id)
        if market.status not in {"draft", "paused"}:
            raise TmargetError("MARKET_NOT_EDITABLE")
        for field in ("title", "description", "category", "close_time"):
            if field in fields and fields[field] is not None:
                setattr(market, field, str(fields[field]))
        if "resolution_criteria" in fields and fields["resolution_criteria"] is not None:
            market.rule.resolution_criteria = str(fields["resolution_criteria"])
        if "source_url" in fields and fields["source_url"] is not None:
            market.rule.source_url = str(fields["source_url"])
        market.updated_at = _now()
        self.repo.update_market(market)
        self.repo.record_admin_action("update_market", market.id, None, fields)
        return market

    def open_market(self, market_id: str) -> TmargetMarket:
        market = self.get_market(market_id)
        if market.status not in {"draft", "paused"}:
            raise TmargetError("MARKET_NOT_OPENABLE")
        market.status = "open"
        market.updated_at = _now()
        self.repo.update_market(market)
        self.repo.record_admin_action("open_market", market.id, None)
        return market

    def pause_market(self, market_id: str) -> TmargetMarket:
        market = self.get_market(market_id)
        if market.status != "open":
            raise TmargetError("MARKET_NOT_PAUSABLE")
        market.status = "paused"
        market.updated_at = _now()
        self.repo.update_market(market)
        self.repo.record_admin_action("pause_market", market.id, None)
        return market

    def close_market(self, market_id: str) -> TmargetMarket:
        market = self.get_market(market_id)
        if market.status not in {"open", "paused"}:
            raise TmargetError("MARKET_NOT_CLOSABLE")
        market.status = "closed"
        market.updated_at = _now()
        self.repo.update_market(market)
        self.repo.record_admin_action("close_market", market.id, None)
        return market

    async def cancel_market(self, market_id: str, ledger: Optional[LedgerService] = None) -> TmargetMarket:
        market = self.get_market(market_id)
        if market.status == "resolved":
            raise TmargetError("CANNOT_CANCEL_RESOLVED_MARKET")
        market.status = "cancelled"
        market.resolved_outcome = "cancelled"
        market.updated_at = _now()
        if ledger is not None:
            await self.refund_market(market, ledger, outcome="cancelled")
        self.repo.update_market(market)
        self.repo.record_admin_action("cancel_market", market.id, None)
        return market

    async def buy(
        self,
        *,
        market_id: str,
        user_id: str,
        outcome: str,
        shares: int,
        ledger: LedgerService,
    ) -> TmargetTrade:
        market = self.get_market(market_id)
        self._validate_trade(market, outcome, shares)
        quote = estimate_trade(market.pool.yes_pool, market.pool.no_pool, side="buy", outcome=outcome, shares=shares)
        try:
            await ledger.mutate(
                user_id=user_id,
                delta=-quote["cost"],
                reason=REASON_TMARKET_BUY_COST,
                ref_type="TMARGET_MARKET",
                ref_id=market.id,
                idempotency_key=f"tmarget:{market.id}:buy:{user_id}:{outcome}:{len(self.trades)}",
                counter_account="POT",
                source_module="tmarget",
            )
        except InsufficientFunds as exc:
            raise TmargetError("INSUFFICIENT_BALANCE") from exc
        trade = self._record_trade(market, user_id, "buy", outcome, shares, quote)
        pos = self._position(user_id, market.id, outcome)
        new_shares = pos.shares + shares
        pos.avg_price = (
            ((pos.avg_price * pos.shares) + (quote["price"] * shares)) / new_shares
            if new_shares else 0
        )
        pos.shares = new_shares
        pos.cost_basis += quote["cost"]
        market.pool.yes_pool = quote["next_yes_pool"]
        market.pool.no_pool = quote["next_no_pool"]
        market.pool.updated_at = _now()
        self.repo.update_pool(market.id, market.pool)
        market.volume += quote["cost"]
        self.repo.update_market(market)
        return trade

    async def sell(
        self,
        *,
        market_id: str,
        user_id: str,
        outcome: str,
        shares: int,
        ledger: LedgerService,
    ) -> TmargetTrade:
        market = self.get_market(market_id)
        self._validate_trade(market, outcome, shares)
        pos = self._position(user_id, market.id, outcome)
        if pos.shares < shares:
            raise TmargetError("INSUFFICIENT_SHARES")
        quote = estimate_trade(market.pool.yes_pool, market.pool.no_pool, side="sell", outcome=outcome, shares=shares)
        await ledger.mutate(
            user_id=user_id,
            delta=quote["cost"],
            reason=REASON_TMARKET_SELL_CREDIT,
            ref_type="TMARGET_MARKET",
            ref_id=market.id,
            idempotency_key=f"tmarget:{market.id}:sell:{user_id}:{outcome}:{len(self.trades)}",
            counter_account="POT",
            source_module="tmarget",
        )
        trade = self._record_trade(market, user_id, "sell", outcome, shares, quote)
        pos.shares -= shares
        pos.cost_basis = max(0, pos.cost_basis - quote["cost"])
        pos.realized_pnl += quote["cost"]
        market.pool.yes_pool = quote["next_yes_pool"]
        market.pool.no_pool = quote["next_no_pool"]
        market.pool.updated_at = _now()
        self.repo.update_pool(market.id, market.pool)
        market.volume += quote["cost"]
        self.repo.update_market(market)
        return trade

    async def resolve_market(
        self,
        *,
        market_id: str,
        outcome: str,
        resolver_notes: str,
        ledger: Optional[LedgerService] = None,
    ) -> TmargetMarket:
        market = self.get_market(market_id)
        if market.status == "resolved":
            return market
        if market.status != "closed":
            raise TmargetError("MARKET_MUST_BE_CLOSED_FIRST")
        if outcome not in {"yes", "no", "cancelled", "invalid"}:
            raise TmargetError("INVALID_RESOLUTION_OUTCOME")
        if not resolver_notes or not resolver_notes.strip():
            raise TmargetError("RESOLVER_NOTES_REQUIRED")
        market.status = "resolving"
        market.resolver_notes = resolver_notes
        market.resolved_outcome = outcome  # type: ignore[assignment]
        market.resolution_time = str(_now())
        if outcome in {"cancelled", "invalid"}:
            if ledger is not None:
                await self.refund_market(market, ledger, outcome=outcome)
        elif ledger is not None:
            await self.settle_market(market, ledger, outcome=outcome)
        market.status = "resolved"
        market.updated_at = _now()
        self.repo.update_market(market)
        self.repo.record_admin_action("resolve_market", market.id, None, {"outcome": outcome})
        return market

    async def settle_market(self, market: TmargetMarket, ledger: LedgerService, *, outcome: str) -> None:
        for pos in list(self.positions.values()):
            if pos.market_id != market.id or pos.settled:
                continue
            if pos.outcome == outcome and pos.shares > 0:
                amount = payout_amount(pos.shares)
                idempotency_key = f"tmarget:{market.id}:settlement:{pos.user_id}:{outcome}"
                await credit_settlement(
                    ledger,
                    user_id=pos.user_id,
                    market_id=market.id,
                    amount=amount,
                    idempotency_key=idempotency_key,
                )
                self.repo.record_settlement(market.id, pos.user_id, outcome, amount, idempotency_key)
                pos.realized_pnl += amount
            pos.settled = True
            self.repo.upsert_position(pos)

    async def refund_market(self, market: TmargetMarket, ledger: LedgerService, *, outcome: str) -> None:
        for pos in list(self.positions.values()):
            if pos.market_id != market.id or pos.refunded:
                continue
            amount = int(pos.cost_basis)
            if amount > 0:
                idempotency_key = f"tmarget:{market.id}:refund:{pos.user_id}:{outcome}:{pos.outcome}"
                await credit_refund(
                    ledger,
                    user_id=pos.user_id,
                    market_id=market.id,
                    amount=amount,
                    idempotency_key=idempotency_key,
                )
                self.repo.record_refund(market.id, pos.user_id, outcome, amount, idempotency_key)
            pos.refunded = True
            self.repo.upsert_position(pos)

    def market_positions(self, market_id: str, user_id: Optional[str] = None) -> list[dict[str, Any]]:
        return [
            pos.to_dict()
            for pos in self.repo.list_market_positions(market_id, user_id)
        ]

    def user_positions(self, user_id: str) -> list[dict[str, Any]]:
        return [pos.to_dict() for pos in self.repo.get_user_positions(user_id)]

    def market_trades(self, market_id: str) -> list[dict[str, Any]]:
        return [trade.to_dict() for trade in self.repo.list_market_trades(market_id)]

    def _validate_trade(self, market: TmargetMarket, outcome: str, shares: int) -> None:
        if market.status != "open":
            raise TmargetError("MARKET_NOT_OPEN")
        if outcome not in {"yes", "no"}:
            raise TmargetError("INVALID_OUTCOME")
        if not isinstance(shares, int) or shares <= 0:
            raise TmargetError("SHARES_MUST_BE_POSITIVE")

    def _position(self, user_id: str, market_id: str, outcome: str) -> TmargetPosition:
        position = self.repo.get_position(user_id, market_id, outcome)
        if position is None:
            position = TmargetPosition(user_id=user_id, market_id=market_id, outcome=outcome)  # type: ignore[arg-type]
            self.repo.upsert_position(position)
        return position

    def _record_trade(self, market: TmargetMarket, user_id: str, side: str, outcome: str, shares: int, quote: dict) -> TmargetTrade:
        trade = TmargetTrade(
            id=_new_id("tm_trade"),
            user_id=user_id,
            market_id=market.id,
            side=side,  # type: ignore[arg-type]
            outcome=outcome,  # type: ignore[arg-type]
            shares=shares,
            price=float(quote["price"]),
            cost=int(quote["cost"]),
            fee=int(quote["fee"]),
            status="filled",
            created_at=_now(),
        )
        return self.repo.create_trade(trade)
