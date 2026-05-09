from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


MarketStatus = Literal["draft", "open", "paused", "closed", "resolving", "resolved", "cancelled"]
Outcome = Literal["yes", "no"]
ResolvedOutcome = Literal["yes", "no", "cancelled", "invalid"]


@dataclass
class TmargetMarketRule:
    market_id: str
    source_url: str
    resolution_criteria: str
    invalid_conditions: str = ""
    timezone: str = "UTC"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TmargetLiquidityPool:
    market_id: str
    yes_pool: float
    no_pool: float
    liquidity_parameter: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TmargetMarket:
    id: str
    slug: str
    title: str
    description: str
    category: str
    status: MarketStatus
    outcome_type: str
    yes_label: str
    no_label: str
    close_time: str
    resolution_time: Optional[str]
    resolved_outcome: Optional[ResolvedOutcome]
    resolver_notes: str
    created_by: str
    created_at: float
    updated_at: float
    rule: TmargetMarketRule
    pool: TmargetLiquidityPool
    volume: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["yes_price"] = None
        data["no_price"] = None
        return data


@dataclass
class TmargetPosition:
    user_id: str
    market_id: str
    outcome: Outcome
    shares: int = 0
    avg_price: float = 0
    realized_pnl: int = 0
    cost_basis: int = 0
    settled: bool = False
    refunded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TmargetTrade:
    id: str
    user_id: str
    market_id: str
    side: Literal["buy", "sell"]
    outcome: Outcome
    shares: int
    price: float
    cost: int
    fee: int
    status: Literal["filled", "rejected"]
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
