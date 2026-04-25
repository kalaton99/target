"""TARGET game constants. v3.2 architecture."""

# Turn timing
TURN_TIMEOUT_MS = 15000          # 15 seconds, hard
TURN_TIMEOUT_REASON = "TURN_TIMEOUT_15S"
TIMEOUT_GRACE_MS = 500           # network jitter tolerance

# Game rules
TARGET_SCORE = 21
JOKERS_IN_DECK = 2
DECK_SIZE_WITH_JOKERS = 54

# Player limits
MIN_PLAYERS = 2
MAX_PLAYERS = 8

# Commissions (basis points)
COMMISSION_PAID_BPS = 1500       # 15%
COMMISSION_FREE_BPS = 2500       # 25%
LOTTERY_BPS = 3000               # 30% of commission

# Server-only action types (clients cannot emit these)
SERVER_ONLY_ACTIONS = {
    "AUTO_STAND_TIMEOUT",
    "AUTO_FOLD_SITOUT",
    "AUTO_CHECK_SITOUT",
    "PHASE_TRANSITION",
    "DEAL",
    "SHOWDOWN",
    "PAYOUT",
}

# Phases
PHASES = ["ANTE", "DEAL", "DRAW", "BETTING", "SHOWDOWN", "PAYOUT", "ENDED"]
