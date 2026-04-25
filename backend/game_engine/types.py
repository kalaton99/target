"""Game engine state + action types (dataclasses)."""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class PlayerState:
    seat_index: int
    user_id: str
    username: str
    balance_at_start: int
    current_bet: int = 0
    total_contributed: int = 0
    cards: List[Dict[str, Any]] = field(default_factory=list)  # face-up to self
    score: int = 0
    soft: bool = False
    busted: bool = False
    disqualified: bool = False
    folded: bool = False
    stood: bool = False           # locked-in for current draw round
    sitting_out: bool = False
    connected: bool = True
    payout: int = 0


@dataclass
class GameState:
    table_id: str
    hand_id: Optional[str] = None
    hand_number: int = 0
    engine_version: str = "1.0.0"
    phase: str = "WAITING"        # WAITING|ANTE|DEAL|DRAW|BETTING|SHOWDOWN|PAYOUT|ENDED
    version: int = 0              # state_version
    players: List[PlayerState] = field(default_factory=list)
    deck: List[Dict[str, Any]] = field(default_factory=list)  # face-down to clients
    pot: int = 0
    current_bet: int = 0
    min_raise: int = 0
    current_turn_seat: Optional[int] = None
    turn_started_at_ms: Optional[int] = None  # epoch ms
    turn_deadline_ms: Optional[int] = None
    rng_commit_hash: Optional[str] = None
    rng_revealed_seed: Optional[str] = None
    rng_nonce: int = 0
    target_score: int = 21
    stake: int = 100              # ante amount
    max_players: int = 8
    table_type: str = "FREE"      # FREE | PAID
    winners: List[str] = field(default_factory=list)
    last_action_summary: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def state_from_dict(d: Dict[str, Any]) -> GameState:
    players = [PlayerState(**p) for p in d.get("players", [])]
    d2 = dict(d)
    d2["players"] = players
    return GameState(**d2)
