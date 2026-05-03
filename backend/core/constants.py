"""TARGET game constants. Aligned to the real TARGET rules (2026-02 rewrite,
2026-05 locked-rules migration).

No fixed `21` target anymore — target_score is per-table from a fixed set.
Authoritative rule doc: `/app/memory/GAME_RULES_LOCKED.md`.
"""
import os
from pathlib import Path

# Load .env explicitly so env-driven constants below resolve correctly
# regardless of import order (core.config also calls load_dotenv but
# constants is sometimes imported before it). Idempotent.
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # noqa: BLE001
    pass

# ---------- Turn timing ----------
TURN_TIMEOUT_MS = 15000          # 15 seconds, hard
TURN_TIMEOUT_REASON = "TURN_TIMEOUT_15S"
TIMEOUT_GRACE_MS = 500           # network jitter tolerance

# ---------- Game rules ----------
VALID_TARGET_SCORES = (30, 50, 100, 250)
DEFAULT_TARGET_SCORE = 30        # used by dev spawn; production must be explicit
JOKERS_IN_DECK = 2
DECK_SIZE_WITH_JOKERS = 54

# ---------- Table sizes locked per target tier (2026-05) ----------
# Source of truth: GAME_RULES_LOCKED.md §2. Server derives `max_players`
# from `target_score` at table-creation; client-supplied values are ignored.
TABLE_SEATS_BY_TARGET = {
    30: 4,
    50: 4,
    100: 5,
    250: 5,
}

# ---------- Player limits ----------
MIN_PLAYERS = 2
MAX_PLAYERS = 5                  # 2026-05: 6/7/8 deprecated per GAME_RULES_LOCKED.md §3

# ---------- Stand threshold (number of stands that trigger SHOWDOWN) ----------
# Indexed by the number of active players entering DRAW (post-betting folds).
# Note: keys 2..5 cover both seat caps AND mid-hand folds — e.g. a 4-seat
# table where one player folds in BETTING_R1 enters DRAW with 3 active.
STAND_THRESHOLD = {2: 1, 3: 2, 4: 3, 5: 3}

# ---------- 51% call rule ----------
CALL_PERCENT_NUM = 51
CALL_PERCENT_DEN = 100

# ---------- Special cards ----------
# Defense / transfer / bust-save trigger:    Hearts-2, Clubs-2
# Forced attack trigger:                     Hearts-10, Clubs-10
DEFENSE_RANK = "2"
DEFENSE_SUITS = ("H", "C")
ATTACK_RANK = "10"
ATTACK_SUITS = ("H", "C")

# ---------- Card face values ----------
FACE_VALUES = {"J": 7, "Q": 8, "K": 9}

# ---------- Commission (basis points) ----------
COMMISSION_PAID_BPS = 1500       # 15%
COMMISSION_FREE_BPS = 2500       # 25%
LOTTERY_BPS = 3000               # 30% of commission

# ---------- Server-only action types (clients cannot emit these) ----------
SERVER_ONLY_ACTIONS = {
    "START_HAND",
    "AUTO_STAND_TIMEOUT",
    "AUTO_FOLD_INSUFFICIENT",
    "DEAL_INITIAL",
    "PHASE_TRANSITION",
    "SHOWDOWN",
    "PAYOUT",
}

# ---------- Phases ----------
PHASES = (
    "WAITING",
    "ANTE",
    "BETTING_R1",
    "DEAL_INITIAL",
    "DRAW",        # legacy interactive HIT/STAND phase — kept for engine
                   # tests and any future single-draw variant. Not entered
                   # by the canonical multi-round flow.
    "DRAW_1",      # 2026-05 multi-round: auto-deal 1 card per in_hand
    "BETTING_R2",  # 2026-05 multi-round
    "DRAW_2",      # 2026-05 multi-round: auto-deal 1 card per in_hand
    "BETTING_R3",  # 2026-05 multi-round
    "SHOWDOWN",
    "PAYOUT",
    "ENDED",
)

# ---------- CPU/bot config (2026-05 — see GAME_RULES_LOCKED.md §5) ----------
# Bots are a dev/testing affordance. Production must run all-human.
# Both env vars default to OFF so production deploys are safe-by-default.
#
# `BOT_COUNT_MAX` is the GLOBAL hard ceiling (across all tables). The
# per-table effective cap is `max_players - 1` (i.e. at least one human
# seat required) and is enforced at lobby-create time. Since the
# largest locked table is 5 seats, the global ceiling is 4 — a single
# human creator plus four bots.
ALLOW_BOTS = bool(int(os.environ.get("TARGET_ALLOW_BOTS", "0")))
BOT_COUNT_MAX = max(0, min(4, int(os.environ.get("TARGET_BOT_COUNT_MAX", "4"))))


def max_bots_for_target(target_score: int) -> int:
    """Per-target bot ceiling derived from the locked seat table:
    always `seats - 1` (the creator occupies the first seat).

    Clamped by the global `BOT_COUNT_MAX` env — so ops can still
    disable the larger-table bot slots without changing the seat table.
    """
    seats = TABLE_SEATS_BY_TARGET.get(target_score)
    if seats is None:
        return 0
    return min(BOT_COUNT_MAX, max(0, seats - 1))


def seats_for_target(target_score: int) -> int:
    """Resolve the locked seat count for a given target score.

    Raises KeyError if `target_score` is not in `VALID_TARGET_SCORES`.
    Callers should validate `target_score` first; this helper is the
    single point of truth for "target → seats".
    """
    return TABLE_SEATS_BY_TARGET[target_score]
