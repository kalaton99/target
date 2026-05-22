from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


JACKGET_MIN_PLAYERS = 2
JACKGET_MAX_PLAYERS = 4
JACKGET_SPINS_PER_PLAYER = 3
JACKGET_REEL_SYMBOLS = (
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "Cherry",
    "Bell",
    "Star",
    "Crown",
    "Diamond",
    "Seven",
)

TableStatus = Literal["waiting", "ready", "in_progress", "settled", "cancelled"]


@dataclass
class JackgetSpin:
    spin_number: int
    user_id: str
    reels: list[str]
    score: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JackgetSeat:
    table_id: str
    user_id: str
    seat_index: int
    username: str = ""
    is_demo: bool = False
    spins: list[JackgetSpin] = field(default_factory=list)
    total_score: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JackgetTable:
    id: str
    creator_user_id: str
    max_players: int = JACKGET_MAX_PLAYERS
    status: TableStatus = "waiting"
    current_turn_user_id: Optional[str] = None
    created_at: float = 0
    started_at: Optional[float] = None
    settled_at: Optional[float] = None
    seats: list[JackgetSeat] = field(default_factory=list)
    winners: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["table_id"] = self.id
        data["min_players"] = JACKGET_MIN_PLAYERS
        data["spins_per_player"] = JACKGET_SPINS_PER_PLAYER
        return data
