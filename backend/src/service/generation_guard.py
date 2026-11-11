"""Local cost protection for plan generation.

A generation spends the API keys *you* put in ``.env``, so this module exists to
stop an accidental loop (a stuck tab, a script with a retry) from quietly burning
your quota: one daily counter per browser and a cap on how many generations may
run at once.

Counters live in this process. Restarting the server clears them, which is the
right behaviour for a single-user tool — it is a seatbelt, not a billing system.
A failed or interrupted generation refunds its slot, so only work that actually
produced a plan counts against you.
"""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

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
        except TimeoutError as exc:
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
            try:
                yield
            except BaseException:
                # Nothing was produced, so the user must not be charged for it.
                # ``BaseException`` covers ``CancelledError`` too: a client that
                # closes the SSE stream mid-generation gets its slot back.
                self._refund(owner_id)
                raise
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

    def _refund(self, owner_id: str) -> None:
        today = datetime.now(UTC).date().isoformat()
        with self._lock:
            day, count = self._counts.get(owner_id, (today, 0))
            if day == today and count > 0:
                self._counts[owner_id] = (today, count - 1)
