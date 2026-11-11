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

    # Quota is per owner, not global.
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


def test_quota_counts_down_per_owner() -> None:
    local = Settings(plan_daily_limit=2)
    guard = GenerationGuard(local)

    async def scenario() -> None:
        async with guard.generation_slot("owner-a"):
            pass
        assert guard.remaining("owner-a") == 1
        async with guard.generation_slot("owner-a"):
            pass
        assert guard.remaining("owner-a") == 0
        with pytest.raises(QuotaExceededError):
            async with guard.generation_slot("owner-a"):
                pass

    asyncio.run(scenario())
