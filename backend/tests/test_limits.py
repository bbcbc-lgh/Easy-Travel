import asyncio

import pytest

from src.api.deps import get_generation_guard
from src.config import Settings, settings
from src.service.generation_guard import GenerationGuard, QuotaExceededError, ServerBusyError


def test_daily_quota_returns_429(owned_client, other_client, plan_payload, offline_mode, monkeypatch) -> None:
    monkeypatch.setattr(settings, "plan_daily_limit", 1)
    get_generation_guard.cache_clear()

    assert owned_client.post("/api/trip/plan", json=plan_payload()).status_code == 200

    blocked = owned_client.post("/api/trip/plan", json=plan_payload())
    assert blocked.status_code == 429
    assert blocked.headers.get("retry-after")

    # The guard is per owner, not global.
    assert other_client.post("/api/trip/plan", json=plan_payload()).status_code == 200


def test_concurrent_generations_are_bounded() -> None:
    local = Settings(
        plan_max_concurrency=1,
        plan_queue_timeout_seconds=0.05,
        plan_daily_limit=10,
    )
    guard = GenerationGuard(local)

    async def scenario() -> None:
        async with guard.generation_slot("owner-a"):
            with pytest.raises(ServerBusyError):
                async with guard.generation_slot("owner-b"):
                    pass

    asyncio.run(scenario())


def test_quota_is_charged_only_for_generations_that_produced_a_plan() -> None:
    guard = GenerationGuard(Settings(plan_daily_limit=2))

    async def scenario() -> None:
        async with guard.generation_slot("owner-a"):
            pass
        async with guard.generation_slot("owner-a"):
            pass
        # Two successful runs: the third is over the daily cap.
        with pytest.raises(QuotaExceededError):
            async with guard.generation_slot("owner-a"):
                pass

    asyncio.run(scenario())


def test_failed_generation_refunds_its_slot() -> None:
    """A crashed generation must not cost the user one of their daily runs."""
    guard = GenerationGuard(Settings(plan_daily_limit=1))

    async def scenario() -> None:
        with pytest.raises(RuntimeError):
            async with guard.generation_slot("owner-a"):
                raise RuntimeError("pipeline exploded")
        # Refunded, so this one is allowed...
        async with guard.generation_slot("owner-a"):
            pass
        # ...and it consumed the single slot in turn.
        with pytest.raises(QuotaExceededError):
            async with guard.generation_slot("owner-a"):
                pass

    asyncio.run(scenario())


def test_cancelled_generation_refunds_its_slot() -> None:
    """Closing the SSE stream mid-generation gets the slot back."""
    guard = GenerationGuard(Settings(plan_daily_limit=1))

    async def scenario() -> None:
        with pytest.raises(asyncio.CancelledError):
            async with guard.generation_slot("owner-a"):
                raise asyncio.CancelledError()
        async with guard.generation_slot("owner-a"):
            pass

    asyncio.run(scenario())


def test_busy_rejection_does_not_consume_quota() -> None:
    """Being turned away because the machine is busy must not spend a daily run."""
    guard = GenerationGuard(Settings(plan_max_concurrency=1, plan_queue_timeout_seconds=0.05, plan_daily_limit=2))

    async def scenario() -> None:
        async with guard.generation_slot("owner-a"):
            with pytest.raises(ServerBusyError):
                async with guard.generation_slot("owner-a"):
                    pass

        # The rejected attempt must not have burned a daily run: this second
        # successful generation is allowed, and it uses up the quota.
        async with guard.generation_slot("owner-a"):
            pass

        with pytest.raises(QuotaExceededError):
            async with guard.generation_slot("owner-a"):
                pass

    asyncio.run(scenario())
