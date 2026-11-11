import asyncio
from datetime import date

from src.api.deps import TripPlanningPipeline
from src.config import Settings
from src.planning.contracts import CandidatePlaces
from src.model.schemas import Attraction, DayPlan, Hotel, Location, Meal, TripPlan, TripPlanRequest


EMPTY_CANDIDATES = CandidatePlaces(attractions=[], hotels=[], meals=[], weather=[])


def request() -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 11, 20),
        days=1,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def meal(name: str, longitude: float, latitude: float) -> Meal:
    return Meal(
        type="lunch",
        name=name,
        address="测试",
        location=Location(longitude=longitude, latitude=latitude),
        estimated_cost=25,
        price_source="estimated",
        source="sample",
    )


def plan_with(meals: list[Meal]) -> TripPlan:
    hotel = Hotel(
        name="测试酒店",
        address="测试",
        location=Location(longitude=120.1500, latitude=30.2700),
        estimated_cost=300,
        source="sample",
    )
    attraction = Attraction(
        name="测试景点",
        address="测试",
        location=Location(longitude=120.1510, latitude=30.2710),
        category="景点",
        source="sample",
    )
    day = DayPlan(
        date="2026-11-20",
        day_index=0,
        description="",
        transportation="公共交通",
        accommodation="经济型酒店",
        hotel=hotel,
        attractions=[attraction],
        meals=meals,
    )
    return TripPlan(
        id="p1",
        city="杭州",
        start_date="2026-11-20",
        end_date="2026-11-20",
        days=[day],
        weather_info=[],
        overall_suggestions="",
    )


def test_far_meals_are_replaced_by_nearby_ones(monkeypatch) -> None:
    """A revision must not keep a meal 120 km away when the day has nearby options."""
    pipeline = TripPlanningPipeline(Settings(use_sample_data=True))
    plan = plan_with([meal("很远餐厅A", 121.5, 31.5), meal("很远餐厅B", 121.6, 31.6), meal("很远餐厅C", 121.7, 31.7)])

    async def fake_around(request, location, radius, limit):
        return [meal("巷口小馆", 120.1515, 30.2715), meal("街角面馆", 120.1508, 30.2706), meal("早餐铺", 120.1502, 30.2702)]

    monkeypatch.setattr(pipeline.meal_agent, "run_around", fake_around)

    picked = asyncio.run(pipeline.enrich_meals(request(), plan, EMPTY_CANDIDATES, {0}))

    names = {item.name for item in plan.days[0].meals}
    assert picked == 1
    assert "巷口小馆" in names
    assert not any("很远" in name for name in names)


def test_untouched_days_keep_their_meals(monkeypatch) -> None:
    pipeline = TripPlanningPipeline(Settings(use_sample_data=True))
    plan = plan_with([meal("很远餐厅A", 121.5, 31.5)])

    async def fake_around(request, location, radius, limit):
        return [meal("巷口小馆", 120.1515, 30.2715)]

    monkeypatch.setattr(pipeline.meal_agent, "run_around", fake_around)

    picked = asyncio.run(pipeline.enrich_meals(request(), plan, EMPTY_CANDIDATES, {1}))

    assert picked == 0
    assert plan.days[0].meals[0].name == "很远餐厅A"


def test_revision_reanchors_only_the_changed_days(
    monkeypatch, owned_client, plan_payload, offline_mode
) -> None:
    """The revise endpoint must feed changed day indexes into meal enrichment."""
    from src.api.deps import get_pipeline
    from src.model.schemas import DayEdit, PlanPatch

    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()
    pipeline = get_pipeline()
    captured: dict = {}

    async def fake_propose(request, plan, candidates, instruction):
        return PlanPatch(days=[DayEdit(day_index=0, description="改成室内")], reply="已调整")

    async def fake_enrich(request, plan, candidates, day_indexes=None):
        captured["days"] = day_indexes
        return 0

    monkeypatch.setattr(pipeline.reviser, "propose", fake_propose)
    monkeypatch.setattr(pipeline, "enrich_meals", fake_enrich)

    response = owned_client.post(
        f"/api/trip/plans/{created['id']}/revise",
        json={"instruction": "第 1 天换成室内"},
    )

    assert response.status_code == 200
    assert "days" not in captured, "a description-only edit needs no new meal anchors"


def test_revision_reanchors_days_whose_places_changed(
    monkeypatch, owned_client, plan_payload, offline_mode
) -> None:
    from src.api.deps import get_pipeline
    from src.model.schemas import DayEdit, PlanPatch

    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()
    pipeline = get_pipeline()
    captured: dict = {}

    async def fake_propose(request, plan, candidates, instruction):
        return PlanPatch(days=[DayEdit(day_index=0, hotel=plan.days[0].hotel.name)], reply="换酒店")

    async def fake_enrich(request, plan, candidates, day_indexes=None):
        captured["days"] = day_indexes
        return 0

    monkeypatch.setattr(pipeline.reviser, "propose", fake_propose)
    monkeypatch.setattr(pipeline, "enrich_meals", fake_enrich)

    response = owned_client.post(
        f"/api/trip/plans/{created['id']}/revise",
        json={"instruction": "第 1 天换一家酒店"},
    )

    assert response.status_code == 200
    assert captured.get("days") == {0}

def test_collect_for_edit_prefers_around_search(monkeypatch) -> None:
    pipeline = TripPlanningPipeline(Settings(use_sample_data=True))
    plan = plan_with([])
    city_pool = CandidatePlaces(
        attractions=[],
        hotels=[],
        meals=[meal("全城餐厅", 121.5, 31.5)],
        weather=[],
    )

    async def fake_collect(request):
        return city_pool

    async def fake_around(request, location, radius, limit):
        return [meal("附近餐厅", 120.1512, 30.2712), meal("街口小馆", 120.1507, 30.2707)]

    monkeypatch.setattr(pipeline, "collect", fake_collect)
    monkeypatch.setattr(pipeline.meal_agent, "run_around", fake_around)

    candidates = asyncio.run(pipeline.collect_for_edit(request(), plan))

    assert [item.name for item in candidates.meals] == ["附近餐厅", "街口小馆"]


def test_collect_for_edit_falls_back_to_city_pool(monkeypatch) -> None:
    pipeline = TripPlanningPipeline(Settings(use_sample_data=True))
    plan = plan_with([])
    city_pool = CandidatePlaces(
        attractions=[],
        hotels=[],
        meals=[meal("全城餐厅", 121.5, 31.5)],
        weather=[],
    )

    async def fake_collect(request):
        return city_pool

    async def fake_around(request, location, radius, limit):
        return []

    monkeypatch.setattr(pipeline, "collect", fake_collect)
    monkeypatch.setattr(pipeline.meal_agent, "run_around", fake_around)

    candidates = asyncio.run(pipeline.collect_for_edit(request(), plan))

    assert [item.name for item in candidates.meals] == ["全城餐厅"]
