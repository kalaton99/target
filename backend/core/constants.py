"""TARGET game constants. Aligned to the real TARGET rules (2026-02 rewrite).

No fixed `21` target anymore — target_score is per-table from a fixed set.
"""

# ---------- Turn timing ----------
TURN_TIMEOUT_MS = 15000          # 15 seconds, hard
TURN_TIMEOUT_REASON = "TURN_TIMEOUT_15S"
# ---------- Legacy compatibility (do not use in new code) ----------
# Pre-2026-02 fixed-target shim — kept so legacy `tables/`, `realtime/`,
# `wallet/` modules continue to import. New engine ignores this entirely.
TARGET_SCORE = 21
TIMEOUT_GRACE_MS = 500

# ---------- Game rules ----------
VALID_TARGET_SCORES = (30, 50, 100, 250)
DEFAULT_TARGET_SCORE = 30        # used by dev spawn; production must be explicit
JOKERS_IN_DECK = 2
DECK_SIZE_WITH_JOKERS = 54

# ---------- Player limits ----------
MIN_PLAYERS = 2
MAX_PLAYERS = 8

# ---------- Stand threshold (number of stands that trigger SHOWDOWN) ----------
# Indexed by the number of active players entering DRAW (post-betting folds).
STAND_THRESHOLD = {2: 1, 3: 2, 4: 3, 5: 3, 6: 4, 7: 4, 8: 5}

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
    "DRAW",
    "SHOWDOWN",
    "PAYOUT",
    "ENDED",
)
