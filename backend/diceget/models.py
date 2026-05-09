from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


SUPPORTED_TARGETS = {30, 50, 75, 100}
DICEGET_SEATS = 4
MAX_BOTS = 3

TableStatus = Literal["waiting", "active", "showdown", "settled", "cancelled"]
SeatStatus = Literal["seated", "active", "held", "busted", "forfeited"]
BotProfile = Literal["safe", "normal", "aggressive"]


@dataclass
class DicegetSeat:
    table_id: str
    user_id: str
    seat_index: int
    username: str = ""
    is_bot: bool = False
    bot_profile: Optional[BotProfile] = None
    status: SeatStatus = "seated"
    score: int = 0
    locked_score: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DicegetRoll:
    round_id: str
    user_id: str
    dice_1: int
    dice_2: int
    total: int
    score_before: int
    score_after: int
    is_bust: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DicegetTable:
    id: str
    target_score: int
    stake: int
    creator_user_id: str
    max_players: int = DICEGET_SEATS
    status: TableStatus = "waiting"
    current_turn_user_id: Optional[str] = None
    turn_index: int = 0
    created_at: float = 0
    started_at: Optional[float] = None
    settled_at: Optional[float] = None
    round_id: str = ""
    seats: list[DicegetSeat] = field(default_factory=list)
    rolls: list[DicegetRoll] = field(default_factory=list)
    winners: list[str] = field(default_factory=list)
    settlement_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["table_id"] = self.id
        return data
