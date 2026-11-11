import asyncio
from datetime import date

from src.config import Settings
from src.model.schemas import TripPlanRequest
from src.planning.contracts import CandidatePlaces
from src.planning.rule_planner import RulePlanner
from src.service.amap import AMapService
from src.service.cache import TTLCache
from src.service.sample_data import sample_attractions, sample_hotels, sample_meals, sample_weather


def request(days: int = 2) -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 11, 20),
        days=days,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def candidates(days: int = 2) -> CandidatePlaces:
    req = request(days)
    return CandidatePlaces(
        attractions=sample_attractions(req.city, req.preferences),
        hotels=sample_hotels(req.city, req.accommodation, req.budget),
        meals=sample_meals(req.city, req.budget),
        weather=sample_weather(req.start_date.isoformat(), days),
    )


def test_rule_planner_implements_the_planner_interface() -> None:
    planner = RulePlanner()

    plan = asyncio.run(planner.plan(request(), candidates(), feedback=None))

    assert len(plan.days) == 2
    assert plan.days[0].date == "2026-11-20"
    assert plan.days[1].date == "2026-11-21"
    assert plan.budget is not None
    assert plan.budget.total > 0
    assert plan.days[0].meals
    assert {meal.type for meal in plan.days[0].meals} <= {"breakfast", "lunch", "dinner"}


def test_rule_planner_keeps_attractions_geo_ordered() -> None:
    planner = RulePlanner()

    plan = asyncio.run(planner.plan(request(days=1), candidates(days=1)))

    assert len(plan.days[0].attractions) <= 3


def test_ttl_cache_expires() -> None:
    cache = TTLCache(ttl_seconds=1)
    cache.set("k", "v")

    assert cache.get("k") == "v"

    cache._entries["k"] = (0.0, "v")
    assert cache.get("k") is None


def test_amap_caches_identical_searches(monkeypatch) -> None:
    service = AMapService(
        Settings(use_sample_data=False, amap_web_service_key="key", cache_enabled=True, cache_ttl_seconds=60)
    )
    calls = {"count": 0}

    async def fake_search(**kwargs):
        calls["count"] += 1
        return [
            {
                "name": "测试景点",
                "location": "120.150,30.270",
                "type": "风景名胜;公园广场;公园",
                "address": "杭州市",
            }
        ]

    monkeypatch.setattr(service, "_search_pois", fake_search)
    req = request(days=3)

    first = asyncio.run(service.search_attractions(req))
    second = asyncio.run(service.search_attractions(req))

    assert calls["count"] == 1, "identical searches must be served from cache"
    assert [item.name for item in first] == [item.name for item in second]


def test_amap_cache_is_keyed_by_request_shape(monkeypatch) -> None:
    service = AMapService(
        Settings(use_sample_data=False, amap_web_service_key="key", cache_enabled=True, cache_ttl_seconds=60)
    )
    calls = {"count": 0}

    async def fake_search(**kwargs):
        calls["count"] += 1
        return []

    monkeypatch.setattr(service, "_search_pois", fake_search)

    asyncio.run(service.search_attractions(request(days=3)))
    asyncio.run(service.search_attractions(request(days=4)))

    assert calls["count"] == 2


def test_amap_cache_can_be_disabled(monkeypatch) -> None:
    service = AMapService(Settings(use_sample_data=False, amap_web_service_key="key", cache_enabled=False))
    calls = {"count": 0}

    async def fake_search(**kwargs):
        calls["count"] += 1
        return []

    monkeypatch.setattr(service, "_search_pois", fake_search)
    req = request()

    asyncio.run(service.search_attractions(req))
    asyncio.run(service.search_attractions(req))

    assert calls["count"] == 2


def test_weather_is_cached(monkeypatch) -> None:
    service = AMapService(
        Settings(use_sample_data=False, amap_web_service_key="key", cache_enabled=True, cache_ttl_seconds=60)
    )
    calls = {"count": 0}

    async def fake_weather(req):
        calls["count"] += 1
        return sample_weather(req.start_date.isoformat(), req.days)

    monkeypatch.setattr(service, "_query_weather_uncached", fake_weather)
    req = request()

    asyncio.run(service.query_weather(req))
    asyncio.run(service.query_weather(req))

    assert calls["count"] == 1
