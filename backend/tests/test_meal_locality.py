import asyncio
from datetime import date

from src.agent.review_agent import ReviewAgent
from src.agent.trip_planning_graph import TripPlanningGraph, _merge_meals
from src.config import Settings
from src.model.schemas import Attraction, DayPlan, Hotel, Location, Meal, TripPlan, TripPlanRequest
from src.planning.critic import PlanCritic
from src.planning.scheduler import haversine_meters, pick_meals
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


HOME = Location(longitude=120.150, latitude=30.270)


def meal(name: str, cost: int, location: Location | None = None) -> Meal:
    return Meal(
        type="lunch",
        name=name,
        address="杭州市",
        location=location,
        estimated_cost=cost,
        price_source="api" if location else "unknown",
        source="amap",
    )


def attraction(name: str = "测试景点") -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=Location(longitude=120.152, latitude=30.272),
        category="博物馆",
        ticket_price=30,
        price_source="api",
        source="amap",
    )


def hotel() -> Hotel:
    return Hotel(
        name="测试酒店",
        address="杭州市",
        location=HOME,
        estimated_cost=300,
        price_source="api",
        source="amap",
    )


# --- around search -----------------------------------------------------------


def poi(name: str, longitude: float, latitude: float, cost: str = "30") -> dict:
    return {
        "name": name,
        "location": f"{longitude},{latitude}",
        "type": "餐饮服务;中餐厅;小吃",
        "address": "杭州市",
        "biz_ext": {"cost": cost},
    }


def test_around_search_returns_located_meals(monkeypatch) -> None:
    service = AMapService(
        Settings(use_sample_data=False, amap_web_service_key="key", cache_enabled=True)
    )
    calls = {"count": 0}

    async def fake_get_json(url, params):
        calls["count"] += 1
        assert "place/around" in url
        assert params["radius"] == 1500
        return {"status": "1", "pois": [poi("巷口包子", 120.151, 30.271, "18")]}

    monkeypatch.setattr(service, "_get_json", fake_get_json)

    meals = asyncio.run(service.search_meals_around(request(), HOME, radius=1500))

    assert len(meals) == 1
    assert meals[0].name == "巷口包子"
    assert meals[0].location is not None
    assert meals[0].price_source == "api"
    assert meals[0].estimated_cost == 18

    # Cached by location + radius: a second identical call must not hit the API.
    asyncio.run(service.search_meals_around(request(), HOME, radius=1500))
    assert calls["count"] == 1


def test_around_search_skips_pois_without_coordinates(monkeypatch) -> None:
    service = AMapService(Settings(use_sample_data=False, amap_web_service_key="key"))

    async def fake_get_json(url, params):
        return {"status": "1", "pois": [{"name": "无坐标餐厅", "type": "餐饮服务"}]}

    monkeypatch.setattr(service, "_get_json", fake_get_json)

    meals = asyncio.run(service.search_meals_around(request(), HOME))

    assert meals == []


# --- distance filtering ------------------------------------------------------


def test_meal_without_coordinates_never_beats_a_nearby_one() -> None:
    nearby = meal("近餐厅", 40, Location(longitude=120.151, latitude=30.271))
    unknown = meal("无坐标餐厅", 20)

    picked = pick_meals([unknown, nearby], request(), hotel(), [attraction()], set())

    assert picked
    assert all(item.name == "近餐厅" for item in picked)


def test_meal_far_from_the_day_is_not_chosen_when_a_near_one_exists() -> None:
    far = meal("远餐厅", 30, Location(longitude=120.60, latitude=30.60))
    near = meal("近餐厅", 45, Location(longitude=120.152, latitude=30.272))

    picked = pick_meals([far, near], request(), hotel(), [attraction()], set())

    assert all(item.name == "近餐厅" for item in picked)


# --- graph node --------------------------------------------------------------


class AroundMealAgent:
    def __init__(self) -> None:
        self.radii: list[int] = []

    async def run(self, req):
        return []

    async def run_around(self, req, location, radius=2000, limit=10):
        self.radii.append(radius)
        return [
            meal("巷口包子", 18, Location(longitude=location.longitude + 0.001, latitude=location.latitude)),
            meal("面馆", 30, Location(longitude=location.longitude + 0.002, latitude=location.latitude)),
            meal("小炒", 50, Location(longitude=location.longitude + 0.003, latitude=location.latitude)),
        ]


class StubAgent:
    async def run(self, req):
        return []


class StubAMap:
    async def enrich_daily_routes(self, plan, req):
        return plan


def build_graph(meal_agent) -> TripPlanningGraph:
    return TripPlanningGraph(
        attraction_agent=StubAgent(),
        weather_agent=StubAgent(),
        hotel_agent=StubAgent(),
        meal_agent=meal_agent,
        planner_agent=StubAgent(),
        review_agent=ReviewAgent(),
        amap_service=StubAMap(),
        critic=PlanCritic(),
        max_revisions=0,
    )


def test_enrich_meals_uses_around_search_and_fills_breaks() -> None:
    plan = TripPlan(
        city="杭州",
        start_date="2026-11-20",
        end_date="2026-11-20",
        days=[
            DayPlan(
                date="2026-11-20",
                day_index=0,
                description="测试",
                transportation="公共交通",
                accommodation="经济型酒店",
                hotel=hotel(),
                attractions=[attraction()],
                meals=[],
            )
        ],
        overall_suggestions="测试",
    )
    agent = AroundMealAgent()

    result = asyncio.run(
        build_graph(agent)._enrich_meals({"request": request(), "plan": plan, "meals": []})
    )
    day = result["plan"].days[0]

    assert {item.type for item in day.meals} == {"breakfast", "lunch", "dinner"}
    assert all(item.location is not None for item in day.meals)
    assert all(
        haversine_meters(attraction().location, item.location) < 1_000 for item in day.meals
    )
    assert 1200 in agent.radii, "breakfast pool must be searched around the hotel"
    assert result["plan"].budget is not None
    assert result["plan"].budget.total_meals > 0


def test_merge_meals_prefers_local_candidates() -> None:
    local = meal("同名餐厅", 30, HOME)
    remote = Meal.model_validate({**local.model_dump(), "estimated_cost": 90})

    merged = _merge_meals([local], [remote])

    assert len(merged) == 1
    assert merged[0].estimated_cost == 30
