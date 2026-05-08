"""Deck builder + provably fair Fisher-Yates shuffle keyed by SHA256 seed."""
import hashlib
from typing import List

from .cards import Card, SUITS, RANKS


def build_fresh_deck(include_jokers: bool = True) -> List[Card]:
    """Build a fresh deck.

    2026-02 (rules tightening): the standard initial deck is 52 cards
    + exactly **one** Joker. The previous 52+2 Joker layout has been
    removed — within a single hand/deck sequence, the engine must
    never deal more than one Joker before a refill (and refills are
    Joker-less per `_refill_deck_if_empty`).
    """
    deck: List[Card] = [Card(r, s) for s in SUITS for r in RANKS]
    if include_jokers:
        deck.append(Card("JOKER", "*"))
    return deck


def shuffle(deck: List[Card], shuffle_seed_hex: str) -> List[Card]:
    """Deterministic Fisher-Yates shuffle.

    Generates a stream of integers from SHA256(seed || counter)
    and swaps using a canonical algorithm. Reproducible.
    """
    arr = list(deck)
    n = len(arr)
    counter = 0
    for i in range(n - 1, 0, -1):
        # Generate next random in [0, i+1) by hashing seed || counter
        while True:
            h = hashlib.sha256(
                f"{shuffle_seed_hex}:{counter}".encode("utf-8")
            ).digest()
            counter += 1
            # Use first 8 bytes as unsigned int
            num = int.from_bytes(h[:8], "big")
            # Reject-sample to avoid modulo bias
            limit = (1 << 64) - ((1 << 64) % (i + 1))
            if num < limit:
                j = num % (i + 1)
                break
        arr[i], arr[j] = arr[j], arr[i]
    return arr


def compute_shuffle_seed(server_seed_hex: str, combined_client_seed_hex: str, nonce: int) -> str:
    s = f"{server_seed_hex}:{combined_client_seed_hex}:{nonce}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
