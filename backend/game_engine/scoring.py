"""TARGET hand scoring.

Card values:
  Number 2..9 = face value
  10           = 10
  J            = 7
  Q            = 8
  K            = 9
  Ace          = 1 or 11 (auto-resolved best non-bust)
  Joker        = instant DISQUALIFICATION
"""
from typing import List, Dict, Any

FACE_VALUES = {"J": 7, "Q": 8, "K": 9}
TARGET = 21


def card_base_value(rank: str) -> int:
    if rank == "JOKER":
        return 0
    if rank == "A":
        return 1  # base; treated as 11 if upgrade fits
    if rank in FACE_VALUES:
        return FACE_VALUES[rank]
    return int(rank)


def score_hand(cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Returns dict: {total, soft, busted, disqualified}.

    cards: list of {"rank":..., "suit":...} dicts.
    """
    if any(c["rank"] == "JOKER" for c in cards):
        return {"total": 0, "soft": False, "busted": False, "disqualified": True}

    total = sum(card_base_value(c["rank"]) for c in cards)
    aces = sum(1 for c in cards if c["rank"] == "A")

    # Promote Aces 1 -> 11 (delta +10 each) while not busting
    soft = False
    while aces > 0 and total + 10 <= TARGET:
        total += 10
        aces -= 1
        soft = True

    busted = total > TARGET
    return {"total": total, "soft": soft, "busted": busted, "disqualified": False}
