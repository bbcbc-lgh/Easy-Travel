"""Candidate admission: what may be offered as a stop.

Two rules learned from a real run: a shopper asked for "购物、美食" and got two
aquariums and a market street, because shopping POIs were excluded by type, by the
admission filter, and by the keyword list. And a spicy fish hotpot was offered as
breakfast, because the deny list only knew the generic words.
"""

from datetime import date

import pytest

from src.model.schemas import TripPlanRequest
from src.planning.scheduler import _is_non_breakfast
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
        # A meal-only preference is not a shopping preference either.
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


class TestBreakfast:
    @pytest.mark.parametrize(
        "name",
        ["鱼蛙兄弟美蛙鱼", "土老肥豆米火锅", "某记干锅牛肉", "烧椒牛肉", "老街烤鱼", "串串香"],
    )
    def test_savoury_dishes_are_not_breakfast(self, name: str) -> None:
        meal = type("M", (), {"name": name, "description": ""})()
        assert _is_non_breakfast(meal) is True

    @pytest.mark.parametrize("name", ["曾记丝娃娃", "包子和豆浆", "老字号米粉", "牛肉粉"])
    def test_ordinary_breakfast_places_are_fine(self, name: str) -> None:
        meal = type("M", (), {"name": name, "description": ""})()
        assert _is_non_breakfast(meal) is False


class TestBalance:
    def test_shopping_may_not_take_the_whole_list(self) -> None:
        """Five malls over three days is the same failure as no malls at all."""
        cap = AMapService._shopping_cap(10)
        assert 0 < cap < 10
        assert AMapService._shopping_cap(2) == 1


class TestBreakfastRadius:
    """A breakfast 3 km away is a stretch; 9 km is not breakfast, it is a detour."""

    def _hotel(self):
        from src.model.schemas import Location

        return type("H", (), {"location": Location(longitude=106.6, latitude=26.6)})()

    def _meal(self, name: str, meters: float):
        from src.model.schemas import Location, Meal

        return Meal(
            type="breakfast",
            name=name,
            address="某路 1 号",
            estimated_cost=15,
            location=Location(longitude=106.6, latitude=26.6 + meters / 111_000),
        )

    def test_two_km_from_the_hotel_is_accepted(self) -> None:
        from src.planning.scheduler import pick_meals

        picked = pick_meals([self._meal("老街米粉", 2_000)], request("购物"), self._hotel(), [], set())

        assert "breakfast" in [meal.type for meal in picked]

    def test_nine_km_away_is_not_breakfast(self) -> None:
        from src.planning.scheduler import pick_meals

        picked = pick_meals([self._meal("老街米粉", 9_000)], request("购物"), self._hotel(), [], set())

        assert "breakfast" not in [meal.type for meal in picked]
