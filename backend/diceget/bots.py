from __future__ import annotations

from .models import BotProfile


PROFILE_HOLD_RATIO: dict[BotProfile, float] = {
    "safe": 0.70,
    "normal": 0.78,
    "aggressive": 0.86,
}


def should_bot_hold(score: int, target_score: int, profile: BotProfile = "normal") -> bool:
    return score >= int(target_score * PROFILE_HOLD_RATIO.get(profile, 0.78))
