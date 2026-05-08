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
    phase: str = "WAITING"          # WAITING|ANTE|BETTING_R1|DEAL_INITIAL|DRAW|DRAW_1|BETTING_R2|DRAW_2|BETTING_R3|SHOWDOWN|PAYOUT|ENDED
    version: int = 0                # state_version
    players: List[PlayerState] = field(default_factory=list)
    deck: List[Dict[str, Any]] = field(default_factory=list)  # face-down to clients
    # 2026-05 rule addition — when the initial deck (52 + 1 Joker = 53
    # cards as of 2026-02) is exhausted mid-hand, the engine refills
    # with a fresh 52-card jokerless deck. `deck_refills` counts
    # refills in the current hand and seeds a deterministic reshuffle
    # so replays reproduce.
    deck_refills: int = 0
    pot: int = 0

    # ---- Betting (Phase 1 → R1; 2026-05 multi-round → R1/R2/R3) ----
    current_call_owed: int = 0      # amount each non-responded player must pay to stay
    last_raise_amount: int = 0      # amount of most recent raise (or initial bet)
    responded_seats: List[int] = field(default_factory=list)  # seats that have answered the latest raise
    # 2026-05 multi-round betting: 0 outside betting; 1/2/3 during BETTING_R{n}.
    # Read by the bridge for client broadcast and by reducer transitions to
    # decide whether the current betting round is the last (R3 → SHOWDOWN).
    betting_round: int = 0

    # ---- Turn ----
    current_turn_seat: Optional[int] = None
    turn_started_at_ms: Optional[int] = None
    turn_deadline_ms: Optional[int] = None

    # ---- Provably fair ----
    rng_commit_hash: Optional[str] = None
    rng_revealed_seed: Optional[str] = None
    rng_nonce: int = 0
    # 2026-05 v2 — per-seat client-seed contribution to the shuffle.
    # `pending_client_seeds` is filled by SUBMIT_CLIENT_SEED actions
    # between hands; START_HAND consumes and freezes it into
    # `client_seeds_used` for replay. Both are seat_index → seed-hex
    # (empty string == no contribution that hand). Keys are stored as
    # `int` in memory; round-tripped via `state_from_dict` below.
    pending_client_seeds: Dict[int, str] = field(default_factory=dict)
    client_seeds_used: Dict[int, str] = field(default_factory=dict)
    # 2026-05 v2 — plain server_seed buffered through the active hand.
    # NEVER broadcast: stripped in `view_filter.public_view`. Promoted
    # to `rng_revealed_seed` (which IS broadcast) at SHOWDOWN/PAYOUT.
    server_seed_buffer: Optional[str] = None

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
    # 2026-05 v2 — JSON serializes int dict keys as strings; convert
    # back to int so reducer code paths that compare against
    # `seat_index` (int) keep working transparently.
    for fld in ("pending_client_seeds", "client_seeds_used"):
        if fld in d2 and isinstance(d2[fld], dict):
            d2[fld] = {int(k): v for k, v in d2[fld].items()}
    return GameState(**d2)
