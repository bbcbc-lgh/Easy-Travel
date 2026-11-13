"""Candidate admission: what may be offered as a stop.

Two rules learned from a real run: a shopper asked for "购物、美食" and got two
aquariums and a market street, because shopping POIs were excluded by type, by the
admission filter, and by the keyword list. And a spicy fish hotpot was offered as
breakfast, because the deny list only knew the generic words.
"""

import asyncio
from datetime import date

import httpx

from src.config import Settings
from src.model.schemas import Attraction, Location, TripPlanRequest
from src.service.amap import AMapService

MALL = {"name": "观山湖万达广场", "type": "购物服务;购物中心;购物中心", "location": "106.6,26.6"}
SUPERMARKET = {"name": "永辉超市", "type": "购物服务;超市;超市", "location": "106.6,26.6"}
MUSEUM = {"name": "贵州博物馆", "type": "科教文化服务;博物馆;博物馆", "location": "106.6,26.6"}


def attraction(name: str, category: str) -> Attraction:
    return Attraction(
        name=name,
        address="贵阳市",
        location=Location(longitude=106.6, latitude=26.6),
        category=category,
        source="amap",
    )


def request(preferences: str) -> TripPlanRequest:
    return TripPlanRequest(
        city="贵阳",
        start_date=date(2026, 12, 1),
        days=3,
        preferences=preferences,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


class TestShopping:
    def test_a_mall_is_only_a_candidate_when_the_user_wants_to_shop(self) -> None:
        assert AMapService._is_attraction_poi(MALL, allow_shopping=True) is True
        assert AMapService._is_attraction_poi(MALL, allow_shopping=False) is False

    def test_a_supermarket_is_never_a_candidate(self) -> None:
        """Shopping means malls, not the nearest grocery store."""
        assert AMapService._is_attraction_poi(SUPERMARKET, allow_shopping=True) is False

    def test_a_museum_stays_a_candidate_either_way(self) -> None:
        assert AMapService._is_attraction_poi(MUSEUM, allow_shopping=False) is True
        assert AMapService._is_attraction_poi(MUSEUM, allow_shopping=True) is True

    def test_the_shopping_poi_type_is_requested_only_for_shoppers(self) -> None:
        assert "060000" in AMapService._attraction_types(request("购物、美食"))
        assert "060000" not in AMapService._attraction_types(request("历史文化"))
        # "美食" alone is not a shopping preference either.
        assert "060000" not in AMapService._attraction_types(request("美食"))

    def test_mall_keywords_are_searched_only_for_shoppers(self) -> None:
        shopping = AMapService._build_attraction_keywords(request("购物"))
        history = AMapService._build_attraction_keywords(request("历史文化"))

        assert any("购物中心" in keyword for keyword in shopping)
        assert not any("购物中心" in keyword for keyword in history)

    def test_a_mall_takes_half_a_day(self) -> None:
        """One mall is a half-day in itself: shops, food, cinema under one roof."""
        assert AMapService._estimate_visit_duration("购物服务;购物中心;购物中心", "万达广场") == 150
        assert AMapService._estimate_visit_duration("科教文化服务;博物馆", "博物馆") == 120


class TestBalance:
    def test_shopping_may_not_take_the_whole_list(self) -> None:
        """Five malls over three days is the same failure as no malls at all."""
        cap = AMapService._shopping_cap(10)
        assert 0 < cap < 10
        assert AMapService._shopping_cap(2) == 1


class TestDiversityTopUp:
    """A museum-only pool cannot yield a nature trip, however well the model chooses."""

    def _service(self) -> AMapService:
        return AMapService(Settings(amap_web_service_key="test-key", cache_enabled=False))

    def _pool(self, count: int = 4) -> list[Attraction]:
        return [attraction(f"博物馆{i}", "科教文化服务;博物馆;博物馆") for i in range(count)]

    def _park(self, name: str) -> dict:
        return {"name": name, "type": "风景名胜;公园广场;公园", "location": "106.6,26.6"}

    def test_a_museum_heavy_pool_is_topped_up_with_parks(self, monkeypatch) -> None:
        service = self._service()
        calls: list[dict] = []

        async def fake_search(**kwargs):
            calls.append(kwargs)
            return [self._park("黔灵山公园"), self._park("观山湖公园")]

        monkeypatch.setattr(service, "_search_pois", fake_search)

        result = asyncio.run(service._top_up_diversity(request("自然风光"), self._pool()))

        assert calls, "the top-up search should have run"
        assert any(item.name == "黔灵山公园" for item in result)
        assert len(result) == 6

    def test_a_history_trip_does_not_get_parks_pushed_at_it(self, monkeypatch) -> None:
        service = self._service()

        async def fake_search(**kwargs):  # pragma: no cover - must not run
            raise AssertionError("no top-up expected for a history trip")

        monkeypatch.setattr(service, "_search_pois", fake_search)

        result = asyncio.run(service._top_up_diversity(request("历史文化"), self._pool()))

        assert len(result) == 4

    def test_a_balanced_pool_is_left_alone(self, monkeypatch) -> None:
        service = self._service()
        pool = [
            attraction("博物馆", "科教文化服务;博物馆;博物馆"),
            attraction("公园", "风景名胜;公园广场;公园"),
            attraction("老街", "购物服务;特色街区"),
            attraction("湖", "风景名胜;公园广场;公园"),
        ]

        async def fake_search(**kwargs):  # pragma: no cover - must not run
            raise AssertionError("no top-up expected: the pool is already mixed")

        monkeypatch.setattr(service, "_search_pois", fake_search)

        result = asyncio.run(service._top_up_diversity(request("自然风光"), pool))

        assert len(result) == 4

    def test_a_place_already_in_the_pool_is_not_added_twice(self, monkeypatch) -> None:
        service = self._service()

        async def fake_search(**kwargs):
            return [self._park("博物馆0")]

        monkeypatch.setattr(service, "_search_pois", fake_search)

        result = asyncio.run(service._top_up_diversity(request("自然风光"), self._pool()))

        assert [item.name for item in result].count("博物馆0") == 1

    def test_a_failed_top_up_leaves_the_pool_untouched(self, monkeypatch) -> None:
        service = self._service()

        async def failing_search(**kwargs):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(service, "_search_pois", failing_search)

        result = asyncio.run(service._top_up_diversity(request("自然风光"), self._pool()))

        assert len(result) == 4

    def test_the_top_up_is_capped(self, monkeypatch) -> None:
        service = self._service()

        async def fake_search(**kwargs):
            return [self._park(f"公园{i}") for i in range(10)]

        monkeypatch.setattr(service, "_search_pois", fake_search)

        result = asyncio.run(service._top_up_diversity(request("休闲"), self._pool()))

        assert len(result) == 4 + 3
