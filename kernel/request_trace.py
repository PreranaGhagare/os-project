"""Bounded request tracing for simulated kernel services."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any


class RequestTracer:
    """Keep correlated request outcomes and their processing durations."""

    def __init__(self, history_limit: int = 500) -> None:
        self.history_limit = history_limit
        self._events: list[dict[str, Any]] = []

    def start(self) -> float:
        return perf_counter()

    def record(
        self,
        *,
        request_id: str,
        request_type: str,
        operation: str,
        started_at: float,
        ok: bool,
        error: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "request_id": request_id,
            "request_type": request_type,
            "operation": operation,
            "ok": ok,
            "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            "error": error,
        }
        self._events.append(event)
        if len(self._events) > self.history_limit:
            del self._events[: len(self._events) - self.history_limit]
        return dict(event)

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events]

    def clear(self) -> None:
        self._events.clear()
