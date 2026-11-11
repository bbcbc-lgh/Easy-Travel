import asyncio

import pytest

import src.service.amap as amap_module
from src.api.deps import get_trip_plan_repository
from src.config import Settings
from src.model.schemas import TripPlanRequest
from src.service.amap import AMapService


def make_request(days: int = 2) -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date="2026-11-20",
        days=days,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences="历史文化",
    )


def test_offline_mode_weather_never_calls_the_network(monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("offline mode must not open a network connection")

    monkeypatch.setattr(amap_module.httpx, "AsyncClient", explode)
    service = AMapService(Settings(use_sample_data=True))

    weather = asyncio.run(service.query_weather(make_request()))

    assert [item.source for item in weather] == ["sample", "sample"]
    assert all(item.forecast_available for item in weather)


def test_repository_uses_the_isolated_database(isolated_database) -> None:
    repository = get_trip_plan_repository()

    assert repository.database_path == isolated_database


def test_dev_database_is_not_written_by_tests(isolated_database) -> None:
    repository = get_trip_plan_repository()

    assert repository.database_path != repository._resolve_database_path("data/easy_travel.sqlite3")
