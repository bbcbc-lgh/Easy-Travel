import asyncio
from datetime import date

from src.config import Settings
from src.model.schemas import TripPlanRequest
from src.service.amap import AMapService


def request() -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 11, 20),
        days=1,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def poi(name: str, longitude: float = 120.15) -> dict:
    return {
        "name": name,
        "location": f"{longitude},30.27",
        "type": "风景名胜;公园广场;公园",
        "address": "杭州市",
        "business": {
            "rating": "4.9",
            "tel": "0571-87179617",
            "keytag": "5A景区",
            "opentime_week": "周一至周日 00:00-24:00",
        },
        "photos": [{"title": "外观", "url": "https://example.test/photo-1.jpg"}],
    }


def service_with(monkeypatch, pois: list[dict]) -> AMapService:
    service = AMapService(Settings(use_sample_data=False, amap_web_service_key="key"))

    async def fake_search(**kwargs):
        return pois

    monkeypatch.setattr(service, "_search_pois", fake_search)
    return service


def test_attraction_carries_photo_phone_and_level(monkeypatch) -> None:
    service = service_with(monkeypatch, [poi("西湖")])

    attractions = asyncio.run(service.search_attractions(request()))

    assert len(attractions) == 1
    attraction = attractions[0]
    assert attraction.image_url == "https://example.test/photo-1.jpg"
    assert attraction.contact_phone == "0571-87179617"
    assert attraction.level == "5A景区"
    assert attraction.opening_hours == "周一至周日 00:00-24:00"
    assert attraction.rating == 4.9


def test_level_is_ignored_when_keytag_is_not_a_grade() -> None:
    plain = poi("某公园")
    plain["business"] = {"keytag": "环境不错", "rating": "4.1"}

    assert AMapService._poi_level(plain) is None


def test_pagination_fetches_a_second_page(monkeypatch) -> None:
    service = AMapService(Settings(use_sample_data=False, amap_web_service_key="key"))
    pages: list[int] = []

    async def fake_search_v5(city, keyword, types, page):
        pages.append(page)
        start = 0 if page == 1 else 20
        return [poi(f"景点{start + index}", 120.15 + index * 0.001) for index in range(20)]

    monkeypatch.setattr(service, "_search_pois_v5", fake_search_v5)

    pois = asyncio.run(service._search_pois("杭州", ["杭州 景点"], "110000", target_count=100))

    assert pages == [1, 2]
    assert len(pois) == 40


def test_pagination_stops_when_a_short_page_is_returned(monkeypatch) -> None:
    service = AMapService(Settings(use_sample_data=False, amap_web_service_key="key"))
    pages: list[int] = []

    async def fake_search_v5(city, keyword, types, page):
        pages.append(page)
        return [poi(f"景点{index}", 120.15 + index * 0.001) for index in range(5)]

    monkeypatch.setattr(service, "_search_pois_v5", fake_search_v5)

    asyncio.run(service._search_pois("杭州", ["杭州 景点"], "110000", target_count=100))

    assert pages == [1]
