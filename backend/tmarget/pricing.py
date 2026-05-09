from __future__ import annotations

import math

MIN_PRICE = 0.01
MAX_PRICE = 0.99
PAYOUT_PER_SHARE = 100


def bounded(value: float) -> float:
    return max(MIN_PRICE, min(MAX_PRICE, value))


def prices(yes_pool: float, no_pool: float) -> tuple[float, float]:
    total = max(yes_pool + no_pool, 1.0)
    yes = bounded(yes_pool / total)
    no = bounded(1.0 - yes)
    return round(yes, 4), round(no, 4)


def estimate_trade(yes_pool: float, no_pool: float, *, side: str, outcome: str, shares: int) -> dict:
    if shares <= 0:
        raise ValueError("SHARES_MUST_BE_POSITIVE")
    yes_price, no_price = prices(yes_pool, no_pool)
    price = yes_price if outcome == "yes" else no_price
    cost = int(math.ceil(shares * price * PAYOUT_PER_SHARE))
    next_yes = yes_pool
    next_no = no_pool
    if side == "buy" and outcome == "yes":
        next_yes += shares
    elif side == "buy" and outcome == "no":
        next_no += shares
    elif side == "sell" and outcome == "yes":
        next_yes = max(1.0, next_yes - shares)
    elif side == "sell" and outcome == "no":
        next_no = max(1.0, next_no - shares)
    else:
        raise ValueError("INVALID_TRADE")
    next_yes_price, next_no_price = prices(next_yes, next_no)
    return {
        "price": price,
        "cost": cost,
        "fee": 0,
        "next_yes_pool": next_yes,
        "next_no_pool": next_no,
        "next_yes_price": next_yes_price,
        "next_no_price": next_no_price,
    }
