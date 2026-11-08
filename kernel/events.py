"""Kernel event history and live subscriptions."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any


class EventHub:
    """Keep a bounded event history and broadcast events to connected clients."""

    def __init__(self, history_limit: int = 500) -> None:
        self._history: deque[dict[str, Any]] = deque(maxlen=history_limit)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, event_type: str, **payload: Any) -> dict[str, Any]:
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            **payload,
        }
        self._history.append(event)
        for subscriber in tuple(self._subscribers):
            subscriber.put_nowait(event)
        return event

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._history)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)
