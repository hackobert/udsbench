"""Einfacher asynchroner Event-Bus (Testlauf-Fortschritt, Verbindungs-/Statusereignisse, Logs)."""

from __future__ import annotations

import asyncio
import time
from typing import Any


class EventBus:
    def __init__(self, queue_size: int = 5000) -> None:
        self._subs: list[asyncio.Queue[dict[str, Any]]] = []
        self.queue_size = queue_size
        self.dropped = 0
        #: synchrone Senken (z. B. Ereignis-Historie)
        self.sinks: list[Any] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self.queue_size)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def publish(self, topic: str, **data: Any) -> None:
        evt = {"topic": topic, "ts": time.time(), **data}
        for sink in list(self.sinks):
            try:
                sink(evt)
            except Exception:  # pragma: no cover
                pass
        for q in list(self._subs):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                self.dropped += 1

    def publish_threadsafe(self, loop: asyncio.AbstractEventLoop, topic: str, **data: Any) -> None:
        loop.call_soon_threadsafe(lambda: self.publish(topic, **data))
