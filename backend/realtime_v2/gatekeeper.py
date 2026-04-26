"""Phase 6 — Connection gatekeeper.

Enforces hard caps on the number of concurrent WebSocket connections
attributable to a single user or a single source IP. Operates entirely
in-process; safe under asyncio concurrency via a single mutex.

Caps are checked-and-claimed atomically: a slot is only reserved when
the cap test passes, so two simultaneous connect attempts cannot both
slip past a single remaining slot.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Dict, Set


# ---------- error taxonomy ----------

class GatekeeperError(Exception):
    pass


class UserCapExceeded(GatekeeperError):
    pass


class IpCapExceeded(GatekeeperError):
    pass


# ---------- internal slot record ----------

@dataclass
class _Slot:
    token: str
    user_id: str
    ip: str


# ---------- gatekeeper ----------

class Gatekeeper:
    """Per-user / per-IP connection cap enforcer.

    All public coroutines are safe to call concurrently.
    """

    def __init__(self, *, max_per_user: int = 2, max_per_ip: int = 8) -> None:
        if max_per_user < 1 or max_per_ip < 1:
            raise ValueError("caps must be >= 1")
        self._max_per_user = int(max_per_user)
        self._max_per_ip = int(max_per_ip)
        self._slots: Dict[str, _Slot] = {}
        self._by_user: Dict[str, Set[str]] = {}
        self._by_ip: Dict[str, Set[str]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user_id: str, ip: str) -> str:
        """Reserve a slot atomically and return its release token.

        Raises UserCapExceeded / IpCapExceeded when caps are full.
        """
        async with self._lock:
            if len(self._by_user.get(user_id, ())) >= self._max_per_user:
                raise UserCapExceeded(f"USER_CAP_EXCEEDED:{user_id}")
            if len(self._by_ip.get(ip, ())) >= self._max_per_ip:
                raise IpCapExceeded(f"IP_CAP_EXCEEDED:{ip}")
            token = uuid.uuid4().hex
            self._slots[token] = _Slot(token=token, user_id=user_id, ip=ip)
            self._by_user.setdefault(user_id, set()).add(token)
            self._by_ip.setdefault(ip, set()).add(token)
            return token

    async def release(self, token: str) -> None:
        """Release a slot. Idempotent — releasing an unknown token is a noop."""
        async with self._lock:
            slot = self._slots.pop(token, None)
            if not slot:
                return
            user_set = self._by_user.get(slot.user_id)
            if user_set is not None:
                user_set.discard(token)
                if not user_set:
                    self._by_user.pop(slot.user_id, None)
            ip_set = self._by_ip.get(slot.ip)
            if ip_set is not None:
                ip_set.discard(token)
                if not ip_set:
                    self._by_ip.pop(slot.ip, None)

    # ---- inspection (test-friendly, no lock needed for read snapshot) ----

    def user_count(self, user_id: str) -> int:
        return len(self._by_user.get(user_id, ()))

    def ip_count(self, ip: str) -> int:
        return len(self._by_ip.get(ip, ()))

    def total(self) -> int:
        return len(self._slots)

    @property
    def max_per_user(self) -> int:
        return self._max_per_user

    @property
    def max_per_ip(self) -> int:
        return self._max_per_ip
