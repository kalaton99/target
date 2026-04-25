"""Provably-fair RNG: commit-reveal SHA256."""
import hashlib
import secrets
from typing import Tuple


def generate_server_seed() -> Tuple[str, str]:
    """Returns (plain_seed_hex, sha256_hash_hex)."""
    plain = secrets.token_hex(32)
    h = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return plain, h


def verify_seed(plain: str, expected_hash: str) -> bool:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest() == expected_hash


def combine_client_seeds(client_seeds: list[str]) -> str:
    if not client_seeds:
        return hashlib.sha256(b"").hexdigest()
    joined = "|".join(client_seeds)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
