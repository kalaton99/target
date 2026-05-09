from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


FLIPGET_SEATS = 2
SIDES = {"heads", "tails"}

TableStatus = Literal["waiting", "ready", "flipping", "settled", "cancelled"]
RoundStatus = Literal["pending", "flipping", "settled"]
Side = Literal["heads", "tails"]


@dataclass
class FlipgetSeat:
    table_id: str
    user_id: str
    seat_index: int
    username: str = ""
    side: Optional[Side] = None
    ready: bool = False
    joined_at: float = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FlipgetRound:
    id: str
    table_id: str
    round_number: int
    status: RoundStatus = "pending"
    result: Optional[Side] = None
    winner_user_id: Optional[str] = None
    loser_user_id: Optional[str] = None
    created_at: float = 0
    settled_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FlipgetTable:
    id: str
    creator_user_id: str
    stake_amount: int
    status: TableStatus = "waiting"
    max_players: int = FLIPGET_SEATS
    created_at: float = 0
    started_at: Optional[float] = None
    settled_at: Optional[float] = None
    seats: list[FlipgetSeat] = field(default_factory=list)
    round: Optional[FlipgetRound] = None
    settlement_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["table_id"] = self.id
        return data
