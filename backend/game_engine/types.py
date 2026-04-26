"""Game engine state + action types (dataclasses)."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set

from core.constants import DEFAULT_TARGET_SCORE


@dataclass
class PlayerState:
    seat_index: int
    user_id: str
    username: str
    balance_at_start: int
    current_bet: int = 0
    total_contributed: int = 0
    cards: List[Dict[str, Any]] = field(default_factory=list)
    score: int = 0
    soft: bool = False
    busted: bool = False
    disqualified: bool = False
    folded: bool = False
    stood: bool = False
    sitting_out: bool = False
    connected: bool = True
    payout: int = 0

    @property
    def in_hand(self) -> bool:
        """Player is still 'in' the hand (not folded / DQ'd / sitting out)."""
        return not (self.folded or self.disqualified or self.sitting_out)

    @property
    def can_draw(self) -> bool:
        """Player is eligible to take a DRAW-phase action this round."""
        return self.in_hand and not (self.busted or self.stood)

    def available_balance(self) -> int:
        return max(0, self.balance_at_start - self.total_contributed)


@dataclass
class GameState:
    table_id: str
    hand_id: Optional[str] = None
    hand_number: int = 0
    engine_version: str = "2.0.0"   # bumped: TARGET-aligned engine
    phase: str = "WAITING"          # WAITING|ANTE|BETTING_R1|DEAL_INITIAL|DRAW|SHOWDOWN|PAYOUT|ENDED
    version: int = 0                # state_version
    players: List[PlayerState] = field(default_factory=list)
    deck: List[Dict[str, Any]] = field(default_factory=list)  # face-down to clients
    pot: int = 0

    # ---- Betting (Phase 1: BETTING_R1) ----
    current_call_owed: int = 0      # amount each non-responded player must pay to stay
    last_raise_amount: int = 0      # amount of most recent raise (or initial bet)
    responded_seats: List[int] = field(default_factory=list)  # seats that have answered the latest raise

    # ---- Turn ----
    current_turn_seat: Optional[int] = None
    turn_started_at_ms: Optional[int] = None
    turn_deadline_ms: Optional[int] = None

    # ---- Provably fair ----
    rng_commit_hash: Optional[str] = None
    rng_revealed_seed: Optional[str] = None
    rng_nonce: int = 0

    # ---- Hand-level config ----
    target_score: int = DEFAULT_TARGET_SCORE   # 30 | 50 | 100 | 250
    stake: int = 100                # ante per player
    max_players: int = 8
    table_type: str = "FREE"        # FREE | PAID

    # ---- Showdown derived ----
    draw_active_count: int = 0      # non-folded players entering DRAW (sets stand-threshold)
    winners: List[str] = field(default_factory=list)
    last_action_summary: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def state_from_dict(d: Dict[str, Any]) -> GameState:
    players = [PlayerState(**p) for p in d.get("players", [])]
    d2 = dict(d)
    d2["players"] = players
    return GameState(**d2)
