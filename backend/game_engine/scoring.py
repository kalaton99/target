"""TARGET hand scoring (target-parametric).

Card values:
  Number 2..9 = face value
  10           = 10
  J            = 7
  Q            = 8
  K            = 9
  Ace          = 1 or 11 (auto-resolved to highest non-bust value)
  Joker        = instant DISQUALIFICATION

`target` is per-table (30 / 50 / 100 / 250) and must be passed explicitly.
"""
from typing import Any, Dict, List

from core.constants import FACE_VALUES


def card_base_value(rank: str) -> int:
    if rank == "JOKER":
        return 0
    if rank == "A":
        return 1  # base; promoted to 11 if it doesn't bust
    if rank in FACE_VALUES:
        return FACE_VALUES[rank]
    return int(rank)


def score_hand(cards: List[Dict[str, Any]], target: int) -> Dict[str, Any]:
    """Returns {total, soft, busted, disqualified} — relative to `target`."""
    if any(c["rank"] == "JOKER" for c in cards):
        return {"total": 0, "soft": False, "busted": False, "disqualified": True}

    total = sum(card_base_value(c["rank"]) for c in cards)
    aces = sum(1 for c in cards if c["rank"] == "A")

    soft = False
    while aces > 0 and total + 10 <= target:
        total += 10
        aces -= 1
        soft = True

    busted = total > target
    return {"total": total, "soft": soft, "busted": busted, "disqualified": False}
