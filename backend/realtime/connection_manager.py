"""WebSocket connection registry. Per-table sets of (user_id, socket)."""
import asyncio
from typing import Any, Dict, Set, Tuple

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        # table_id -> set of (user_id, websocket)
        self._tables: Dict[str, Set[Tuple[str, WebSocket]]] = {}
        # (user_id) -> count
        self._user_conns: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def add(self, table_id: str, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._tables.setdefault(table_id, set()).add((user_id, ws))
            self._user_conns[user_id] = self._user_conns.get(user_id, 0) + 1

    async def remove(self, table_id: str, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            s = self._tables.get(table_id)
            if s and (user_id, ws) in s:
                s.discard((user_id, ws))
                if not s:
                    self._tables.pop(table_id, None)
            self._user_conns[user_id] = max(0, self._user_conns.get(user_id, 0) - 1)
            if self._user_conns.get(user_id, 0) == 0:
                self._user_conns.pop(user_id, None)

    def user_conn_count(self, user_id: str) -> int:
        return self._user_conns.get(user_id, 0)

    def members(self, table_id: str) -> Set[Tuple[str, WebSocket]]:
        return set(self._tables.get(table_id, set()))

    async def broadcast(self, table_id: str, payload_factory) -> None:
        """payload_factory(user_id) -> dict ; sends per-user filtered payload."""
        members = self.members(table_id)
        for user_id, ws in members:
            try:
                await ws.send_json(payload_factory(user_id))
            except Exception:
                pass

    async def send_to_user(self, table_id: str, user_id: str, payload: Dict[str, Any]) -> None:
        for uid, ws in self.members(table_id):
            if uid == user_id:
                try:
                    await ws.send_json(payload)
                except Exception:
                    pass


manager = ConnectionManager()
