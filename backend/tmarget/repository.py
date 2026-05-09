from __future__ import annotations

import copy
import time
from typing import Any, Optional

from .models import TmargetLiquidityPool, TmargetMarket, TmargetPosition, TmargetTrade


class InMemoryTmargetRepository:
    """Demo storage boundary for Tmarget.

    This repository intentionally keeps the current MVP in memory while giving
    the service a durable-storage seam for the next phase. It is not shared with
    Axwins game modules and should be replaced by a DB-backed implementation
    before production use.
    """

    def __init__(self):
        self.markets: dict[str, TmargetMarket] = {}
        self.positions: dict[tuple[str, str, str], TmargetPosition] = {}
        self.trades: list[TmargetTrade] = []
        self.settlements: list[dict[str, Any]] = []
        self.refunds: list[dict[str, Any]] = []
        self.admin_actions: list[dict[str, Any]] = []

    def create_market(self, market: TmargetMarket) -> TmargetMarket:
        self.markets[market.id] = market
        return market

    def get_market(self, market_id_or_slug: str) -> Optional[TmargetMarket]:
        if market_id_or_slug in self.markets:
            return self.markets[market_id_or_slug]
        for market in self.markets.values():
            if market.slug == market_id_or_slug:
                return market
        return None

    def list_markets(self) -> list[TmargetMarket]:
        return list(self.markets.values())

    def update_market(self, market: TmargetMarket) -> TmargetMarket:
        self.markets[market.id] = market
        return market

    def create_trade(self, trade: TmargetTrade) -> TmargetTrade:
        self.trades.append(trade)
        return trade

    def list_market_trades(self, market_id: str) -> list[TmargetTrade]:
        return [trade for trade in self.trades if trade.market_id == market_id]

    def get_user_positions(self, user_id: str) -> list[TmargetPosition]:
        return [pos for pos in self.positions.values() if pos.user_id == user_id]

    def list_market_positions(self, market_id: str, user_id: Optional[str] = None) -> list[TmargetPosition]:
        return [
            pos
            for pos in self.positions.values()
            if pos.market_id == market_id and (user_id is None or pos.user_id == user_id)
        ]

    def get_position(self, user_id: str, market_id: str, outcome: str) -> Optional[TmargetPosition]:
        return self.positions.get((user_id, market_id, outcome))

    def upsert_position(self, position: TmargetPosition) -> TmargetPosition:
        self.positions[(position.user_id, position.market_id, position.outcome)] = position
        return position

    def get_pool(self, market_id: str) -> Optional[TmargetLiquidityPool]:
        market = self.markets.get(market_id)
        return market.pool if market else None

    def update_pool(self, market_id: str, pool: TmargetLiquidityPool) -> TmargetLiquidityPool:
        market = self.markets[market_id]
        market.pool = pool
        self.markets[market_id] = market
        return pool

    def record_settlement(self, market_id: str, user_id: str, outcome: str, amount: int, idempotency_key: str) -> None:
        self.settlements.append({
            "market_id": market_id,
            "user_id": user_id,
            "outcome": outcome,
            "amount": int(amount),
            "idempotency_key": idempotency_key,
            "created_at": time.time(),
        })

    def record_refund(self, market_id: str, user_id: str, outcome: str, amount: int, idempotency_key: str) -> None:
        self.refunds.append({
            "market_id": market_id,
            "user_id": user_id,
            "outcome": outcome,
            "amount": int(amount),
            "idempotency_key": idempotency_key,
            "created_at": time.time(),
        })

    def record_admin_action(self, action: str, market_id: Optional[str], user_id: Optional[str], details: Optional[dict[str, Any]] = None) -> None:
        self.admin_actions.append({
            "action": action,
            "market_id": market_id,
            "user_id": user_id,
            "details": copy.deepcopy(details or {}),
            "created_at": time.time(),
        })

    def list_admin_actions(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.admin_actions)
