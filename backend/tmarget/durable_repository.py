"""Inactive durable repository skeleton for Tmarget.

This adapter is not active. No durable backend is configured, no Mongo/Postgres
dependency is introduced, and `InMemoryTmargetRepository` remains the active
runtime repository. This file is a fail-closed contract placeholder only and is
not production persistence.
"""

from __future__ import annotations

from typing import Any, Optional

from .models import TmargetLiquidityPool, TmargetMarket, TmargetPosition, TmargetTrade


class DurableTmargetRepository:
    """Passive durable adapter skeleton.

    The class mirrors the public `InMemoryTmargetRepository` contract so a
    future durable adapter can be implemented deliberately behind the same
    service boundary. Every method fails closed until a real adapter is scoped,
    implemented, tested, and explicitly activated.
    """

    def _inactive(self) -> None:
        raise NotImplementedError(
            "DurableTmargetRepository is an inactive skeleton. "
            "InMemoryTmargetRepository remains the active runtime repository."
        )

    def create_market(self, market: TmargetMarket) -> TmargetMarket:
        self._inactive()

    def get_market(self, market_id_or_slug: str) -> Optional[TmargetMarket]:
        self._inactive()

    def get_market_by_slug(self, slug: str) -> Optional[TmargetMarket]:
        self._inactive()

    def list_markets(self, *, status: Optional[str] = None, category: Optional[str] = None) -> list[TmargetMarket]:
        self._inactive()

    def update_market(self, market: TmargetMarket) -> TmargetMarket:
        self._inactive()

    def create_trade(self, trade: TmargetTrade) -> TmargetTrade:
        self._inactive()

    def list_market_trades(self, market_id: str) -> list[TmargetTrade]:
        self._inactive()

    def get_user_positions(self, user_id: str) -> list[TmargetPosition]:
        self._inactive()

    def list_market_positions(self, market_id: str, user_id: Optional[str] = None) -> list[TmargetPosition]:
        self._inactive()

    def get_position(self, user_id: str, market_id: str, outcome: str) -> Optional[TmargetPosition]:
        self._inactive()

    def upsert_position(self, position: TmargetPosition) -> TmargetPosition:
        self._inactive()

    def get_pool(self, market_id: str) -> Optional[TmargetLiquidityPool]:
        self._inactive()

    def update_pool(self, market_id: str, pool: TmargetLiquidityPool) -> TmargetLiquidityPool:
        self._inactive()

    def record_settlement(self, market_id: str, user_id: str, outcome: str, amount: int, idempotency_key: str) -> dict[str, Any]:
        self._inactive()

    def has_settlement(self, idempotency_key: str) -> bool:
        self._inactive()

    def record_refund(self, market_id: str, user_id: str, outcome: str, amount: int, idempotency_key: str) -> dict[str, Any]:
        self._inactive()

    def has_refund(self, idempotency_key: str) -> bool:
        self._inactive()

    def record_admin_action(self, action: str, market_id: Optional[str], user_id: Optional[str], details: Optional[dict[str, Any]] = None) -> None:
        self._inactive()

    def list_admin_actions(self) -> list[dict[str, Any]]:
        self._inactive()

    def record_status_history(
        self,
        *,
        market_id: str,
        from_status: Optional[str],
        to_status: str,
        changed_by: Optional[str],
        reason: str,
    ) -> dict[str, Any]:
        self._inactive()

    def list_status_history(self, market_id: str) -> list[dict[str, Any]]:
        self._inactive()


TmargetDurableRepository = DurableTmargetRepository


__all__ = ["DurableTmargetRepository", "TmargetDurableRepository"]
