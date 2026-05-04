"""Filter game state for per-player privacy.

Only the local player sees their own cards face-up; opponents always show
card_count and face-down.
"""
from typing import Any, Dict
from copy import deepcopy

from .types import GameState


def public_view(state: GameState, viewer_user_id: str | None) -> Dict[str, Any]:
    s = deepcopy(state.to_dict())
    # 2026-05 v2 — keep `deck` private during play; expose the REMAINING
    # deck only at SHOWDOWN/PAYOUT so an external verifier can confirm
    # the exact ordered shuffle (the verifier reproduces the full deck
    # from server_seed + client_seeds + nonce; the suffix should equal
    # the remaining deck broadcast here).
    if state.phase not in ("SHOWDOWN", "PAYOUT"):
        s.pop("deck", None)
    # `server_seed_buffer` is the plain server seed kept in-state during
    # an active hand for later reveal. It is NEVER broadcast. Once
    # SHOWDOWN/PAYOUT fires, the reducer copies it into
    # `rng_revealed_seed`, which IS broadcast.
    s.pop("server_seed_buffer", None)
    for p in s["players"]:
        if p["user_id"] != viewer_user_id:
            p["card_count"] = len(p["cards"])
            p["cards"] = []
    return s
