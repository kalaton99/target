"""Filter game state for per-player privacy.

Only the local player sees their own cards face-up; opponents always show
card_count and face-down.
"""
from typing import Any, Dict
from copy import deepcopy

from .types import GameState


def public_view(state: GameState, viewer_user_id: str | None) -> Dict[str, Any]:
    s = deepcopy(state.to_dict())
    s.pop("deck", None)  # never expose deck
    # 2026-05 v2 — server_seed_buffer is the plain server seed kept
    # in-state during an active hand for later reveal. It is NEVER
    # broadcast. Once SHOWDOWN/PAYOUT fires, the reducer copies it
    # into `rng_revealed_seed`, which IS broadcast.
    s.pop("server_seed_buffer", None)
    for p in s["players"]:
        if p["user_id"] != viewer_user_id:
            p["card_count"] = len(p["cards"])
            p["cards"] = []
    return s
