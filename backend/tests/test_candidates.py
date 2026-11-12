"""Candidate admission: what may be offered as a stop.

Two rules learned from a real run: a shopper asked for "购物、美食" and got two
aquariums and a market street, because shopping POIs were excluded by type, by the
admission filter, and by the keyword list. And a spicy fish hotpot was offered as
breakfast, because the deny list only knew the generic words.
"""

from datetime import date

from src.model.schemas import TripPlanRequest
from src.service.amap import AMapService

MALL = {"name": "观山湖万达广场", "type": "购物服务;购物中心;购物中心", "location": "106.6,26.6"}
SUPERMARKET = {"name": "永辉超市", "type": "购物服务;超市;超市", "location": "106.6,26.6"}
MUSEUM = {"name": "贵州博物馆", "type": "科教文化服务;博物馆;博物馆", "location": "106.6,26.6"}


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
