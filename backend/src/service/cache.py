"""A tiny in-process TTL cache.

The external data (POIs, weather, routes) changes slowly compared to a single
planning session, and one plan makes dozens of calls. Caching by request shape
removes both latency and quota burn without adding infrastructure.
"""

import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float, max_entries: int = 1024) -> None:
        self.ttl_seconds = max(ttl_seconds, 1.0)
        self.max_entries = max_entries
        self._entries: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            self._entries.pop(key, None)
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        if len(self._entries) >= self.max_entries:
            self._prune()
        self._entries[key] = (time.monotonic() + self.ttl_seconds, value)

    def clear(self) -> None:
        self._entries.clear()

    def _prune(self) -> None:
        now = time.monotonic()
        self._entries = {key: entry for key, entry in self._entries.items() if entry[0] >= now}
        if len(self._entries) >= self.max_entries:
            # Still full: drop the oldest half rather than growing without bound.
            oldest = sorted(self._entries.items(), key=lambda item: item[1][0])
            for key, _ in oldest[: len(oldest) // 2 or 1]:
                self._entries.pop(key, None)
