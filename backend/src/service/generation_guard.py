"""Per-owner quota and global concurrency for plan generation.

Counters live in this process: adequate for a single-worker deployment, and the
interface is what a Redis-backed implementation would expose later.
"""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import AsyncIterator

from src.config import Settings
from src.service.logging import log_event

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__("daily quota exceeded")
        self.limit = limit


class ServerBusyError(Exception):
    def __init__(self, timeout_seconds: float) -> None:
        super().__init__("generation queue is full")
        self.timeout_seconds = timeout_seconds


class GenerationGuard:
    def __init__(self, settings: Settings):
        self.daily_limit = settings.plan_daily_limit
        self.max_concurrency = max(1, settings.plan_max_concurrency)
        self.queue_timeout_seconds = settings.plan_queue_timeout_seconds
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._counts: dict[str, tuple[str, int]] = {}
        self._lock = threading.Lock()

    @asynccontextmanager
    async def generation_slot(self, owner_id: str) -> AsyncIterator[None]:
        """Reserve one generation slot for ``owner_id``; release it on exit."""
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_timeout_seconds)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            log_event(
                logger,
                "limit.busy",
                level=logging.WARNING,
                owner_id=owner_id,
                max_concurrency=self.max_concurrency,
                queue_timeout_seconds=self.queue_timeout_seconds,
            )
            raise ServerBusyError(self.queue_timeout_seconds) from exc

        try:
            self._consume(owner_id)
            yield
        finally:
            self._semaphore.release()

    def _consume(self, owner_id: str) -> None:
        today = datetime.now(UTC).date().isoformat()
        with self._lock:
            day, count = self._counts.get(owner_id, (today, 0))
            if day != today:
                count = 0
            if count >= self.daily_limit:
                log_event(
                    logger,
                    "limit.quota_exceeded",
                    level=logging.WARNING,
                    owner_id=owner_id,
                    daily_limit=self.daily_limit,
                )
                raise QuotaExceededError(self.daily_limit)
            self._counts[owner_id] = (today, count + 1)

    def remaining(self, owner_id: str) -> int:
        today = datetime.now(UTC).date().isoformat()
        with self._lock:
            day, count = self._counts.get(owner_id, (today, 0))
            if day != today:
                return self.daily_limit
            return max(self.daily_limit - count, 0)
