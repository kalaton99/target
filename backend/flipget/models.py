from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


FLIPGET_SEATS = 2
SIDES = {"heads", "tails"}
FLIPGET_MODES = {
    "single_flip": {"label": "Single Flip", "max_rounds": 1, "wins_required": 1},
    "best_of_3": {"label": "Best of 3", "max_rounds": 3, "wins_required": 2},
    "best_of_5": {"label": "Best of 5", "max_rounds": 5, "wins_required": 3},
}

TableStatus = Literal["waiting", "ready", "flipping", "settled", "cancelled"]
RoundStatus = Literal["pending", "flipping", "settled"]
Side = Literal["heads", "tails"]
FlipgetMode = Literal["single_flip", "best_of_3", "best_of_5"]


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
    side_by_user: dict[str, Side] = field(default_factory=dict)
    created_at: float = 0
    settled_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FlipgetTable:
    id: str
    creator_user_id: str
    stake_amount: int
    mode: FlipgetMode = "single_flip"
    status: TableStatus = "waiting"
    max_players: int = FLIPGET_SEATS
    created_at: float = 0
    started_at: Optional[float] = None
    settled_at: Optional[float] = None
    seats: list[FlipgetSeat] = field(default_factory=list)
    round: Optional[FlipgetRound] = None
    rounds: list[FlipgetRound] = field(default_factory=list)
    score: dict[str, int] = field(default_factory=lambda: {"heads": 0, "tails": 0})
    winning_side: Optional[Side] = None
    settlement_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        config = FLIPGET_MODES[self.mode]
        data["table_id"] = self.id
        data["mode_label"] = config["label"]
        data["max_rounds"] = config["max_rounds"]
        data["wins_required"] = config["wins_required"]
        data["current_round_number"] = self.round.round_number if self.round else 0
        return data
