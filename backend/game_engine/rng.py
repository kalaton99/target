"""Provably-fair RNG: commit-reveal SHA256 + per-seat client-seed contribution.

2026-05 v2 — `combine_client_seeds_by_seat` is the canonical combiner used
by the reducer at `START_HAND`. It accepts a `{seat_index: client_seed}`
mapping plus the ordered seat list (so seats with no contribution are
represented as empty strings in the ordered tuple). The output is a
deterministic hex string that, together with `server_seed` and `nonce`,
fully determines the initial deck order.
"""
import hashlib
import secrets
from typing import Dict, Iterable, Tuple


def generate_server_seed() -> Tuple[str, str]:
    """Returns (plain_seed_hex, sha256_hash_hex)."""
    plain = secrets.token_hex(32)
    h = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return plain, h


def verify_seed(plain: str, expected_hash: str) -> bool:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest() == expected_hash


def combine_client_seeds(client_seeds: list[str]) -> str:
    """Legacy positional combiner. Kept for back-compat with replay
    logs that recorded the pre-2026-05-v2 string form. Prefer
    `combine_client_seeds_by_seat` for new code paths.
    """
    if not client_seeds:
        return hashlib.sha256(b"").hexdigest()
    joined = "|".join(client_seeds)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def combine_client_seeds_by_seat(
    client_seeds_by_seat: Dict[int, str], seat_order: Iterable[int],
) -> str:
    """Canonical combiner used by START_HAND.

    For each seat in `seat_order` (ascending seat-index, which matches
    the order players are seated at the table), append
    `seat_index:client_seed_or_empty` separated by `|`. SHA-256 the
    UTF-8 encoding of the full string. The seat-index prefix prevents
    a player from "spoofing" another player's contribution by
    submitting a seed-string containing pipes.

    Seats that did not contribute show up as `seat:` (empty trailing
    segment) so adding/removing a contribution always changes the
    digest.
    """
    parts = []
    for seat in seat_order:
        s = client_seeds_by_seat.get(seat) or ""
        # Defensive: strip any chars that would corrupt the canonical form.
        # The frontend should already lower-case-hex these but we accept
        # any string and just disallow the `|` and `:` separators.
        s_clean = s.replace("|", "").replace(":", "")
        parts.append(f"{seat}:{s_clean}")
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
