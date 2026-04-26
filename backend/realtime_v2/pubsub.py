"""Phase 6 — In-process pub/sub bridge.

Topic-based broadcast for the single-instance MVP. Each subscriber gets
its own bounded asyncio.Queue. `publish` is non-blocking: messages are
dropped per-subscriber when its queue is full so a slow consumer cannot
stall the producer (engine).

This module knows nothing about WebSockets. It is a pure plumbing
primitive that the gateway and the engine use to hand messages back and
forth without import cycles.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Set


class PubSub:
    """Async topic broadcaster with bounded per-subscriber queues."""

    def __init__(self, *, queue_max: int = 256) -> None:
        if queue_max < 1:
            raise ValueError("queue_max must be >= 1")
        self._topics: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._queue_max = int(queue_max)
        # Diagnostic counter; tests use it to assert the slow-consumer policy.
        self._drops: int = 0

    async def subscribe(self, topic: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_max)
        async with self._lock:
            self._topics.setdefault(topic, set()).add(q)
        return q

    async def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        async with self._lock:
            subs = self._topics.get(topic)
            if not subs:
                return
            subs.discard(q)
            if not subs:
                self._topics.pop(topic, None)

    async def publish(self, topic: str, message: Any) -> int:
        """Deliver `message` to all subscribers of `topic`. Returns the
        number of subscribers that received it (queue-full subscribers
        are skipped and counted in `drops`).
        """
        async with self._lock:
            subs = list(self._topics.get(topic, ()))
        delivered = 0
        for q in subs:
            try:
                q.put_nowait(message)
                delivered += 1
            except asyncio.QueueFull:
                self._drops += 1
        return delivered

    # ---- inspection ----

    def subscriber_count(self, topic: str) -> int:
        return len(self._topics.get(topic, ()))

    @property
    def drops(self) -> int:
        return self._drops
