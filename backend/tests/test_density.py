from datetime import date

from src.model.schemas import Attraction, DayPlan, Location, Meal, TripPlan, TripPlanRequest
from src.planning.critic import PlanCritic
from src.planning.density import (
    DAILY_LOAD_LIMIT,
    HEAVY_LOAD,
    LIGHT_LOAD,
    MEDIUM_LOAD,
    attraction_load,
    day_load,
)
from src.planning.scheduler import enforce_load


def attraction(name: str, category: str) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=Location(longitude=120.15, latitude=30.27),
        category=category,
        source="amap",
    )


def day(*attractions: Attraction) -> DayPlan:
    return DayPlan(
        date="2026-11-23",
        day_index=0,
        description="测试",
        transportation="公共交通",
        accommodation="经济型酒店",
        attractions=list(attractions),
        meals=[
            Meal(type="breakfast", name="早餐", address="杭州市", estimated_cost=20, source="amap"),
            Meal(type="lunch", name="午餐", address="杭州市", estimated_cost=40, source="amap"),
            Meal(type="dinner", name="晚餐", address="杭州市", estimated_cost=60, source="amap"),
        ],
    )


def test_weights_follow_venue_type() -> None:
    assert attraction_load(attraction("国家博物馆", "科教文化服务;博物馆")) == HEAVY_LOAD
    assert attraction_load(attraction("西湖", "风景名胜;公园广场;公园")) == MEDIUM_LOAD
    assert attraction_load(attraction("老街", "购物服务;特色街区")) == LIGHT_LOAD
    assert attraction_load(attraction("某处", "未知类型")) == 1.0


def test_three_museums_exceed_the_daily_budget() -> None:
    plan_day = day(
        attraction("国博", "博物馆"),
        attraction("故宫", "宫殿"),
        attraction("养心殿", "博物馆"),
    )

    assert day_load(plan_day) == 6.0
    assert day_load(plan_day) > DAILY_LOAD_LIMIT


def test_three_light_stops_stay_within_budget() -> None:
    plan_day = day(
        attraction("老街", "特色街区"),
        attraction("市集", "购物服务;市集"),
        attraction("湖滨步行街", "购物服务;步行街"),
    )

    assert day_load(plan_day) <= DAILY_LOAD_LIMIT


def test_enforce_load_rebalances_or_drops_stops() -> None:
    museums = [attraction(f"博物馆{i}", "博物馆") for i in range(4)]

    groups = enforce_load([museums[:2], museums[2:]], attraction_load, DAILY_LOAD_LIMIT)

    assert all(sum(attraction_load(item) for item in group) <= DAILY_LOAD_LIMIT for group in groups)
    assert all(len(group) <= 3 for group in groups)


def test_enforce_load_keeps_one_heavy_stop() -> None:
    groups = enforce_load([[attraction("国博", "博物馆")]], attraction_load, DAILY_LOAD_LIMIT)

    assert len(groups[0]) == 1


def build_plan(day_plan: DayPlan) -> TripPlan:
    return TripPlan(
        city="杭州",
        start_date="2026-11-23",
        end_date="2026-11-23",
        days=[day_plan],
        overall_suggestions="测试",
    )


def request() -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 11, 23),
        days=1,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def test_critic_notes_an_overloaded_day_without_forcing_a_replan() -> None:
    plan = build_plan(day(attraction("国博", "博物馆"), attraction("故宫", "宫殿"), attraction("养心殿", "博物馆")))

    critique = PlanCritic().review(request(), plan)

    assert any("走不完" in note for note in critique.notes)
    assert critique.needs_revision is False, "overload is a note, not a reason to re-plan"
