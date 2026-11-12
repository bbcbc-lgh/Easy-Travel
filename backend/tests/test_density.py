from datetime import date

from src.model.schemas import Attraction, DayPlan, Location, PlanQuality, TripPlan, TripPlanRequest
from src.planning.critic import PlanCritic, attach_critique
from src.planning.density import (
    DAILY_LOAD_LIMIT,
    HEAVY_LOAD,
    LIGHT_LOAD,
    MEDIUM_LOAD,
    attraction_load,
    day_load,
    trim_days_to_load,
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


def test_critic_treats_an_overloaded_day_as_a_reason_to_replan() -> None:
    """Overload is the model's own choice of stops, so it is fixable by the model.

    This used to be a note, which meant the pipeline only warned the user. A live
    eval run showed every model-built plan over-packing its days while the rule
    planner, which enforces the limit, never did - so it now asks for one replan.
    """
    plan = build_plan(day(attraction("国博", "博物馆"), attraction("故宫", "宫殿"), attraction("养心殿", "博物馆")))

    critique = PlanCritic().review(request(), plan)

    assert any("走不完" in issue for issue in critique.issues)
    assert critique.needs_revision is True


def test_an_unfixable_overload_still_reaches_the_user() -> None:
    """With no retry left, the issue must show up as a warning instead of vanishing."""
    plan = build_plan(day(attraction("国博", "博物馆"), attraction("故宫", "宫殿"), attraction("养心殿", "博物馆")))
    plan.quality = PlanQuality(score=90, warnings=[], checks={})

    critique = PlanCritic().review(request(), plan)
    attach_critique(plan, critique, will_retry=False)

    assert any("未能自动修正" in warning for warning in plan.quality.warnings)
    assert any("走不完" in warning for warning in plan.quality.warnings)


def test_trim_drops_stops_until_the_day_fits() -> None:
    plan = build_plan(day(attraction("国博", "博物馆"), attraction("故宫", "宫殿"), attraction("养心殿", "博物馆")))
    assert day_load(plan.days[0]) > DAILY_LOAD_LIMIT

    removed = trim_days_to_load(plan)

    assert day_load(plan.days[0]) <= DAILY_LOAD_LIMIT
    assert removed
    assert all("已移除" in message for message in removed)
    assert any("养心殿" in message for message in removed)


def test_trim_leaves_a_fitting_day_alone() -> None:
    plan = build_plan(day(attraction("公园", "公园"), attraction("街区", "步行街")))
    before = [item.name for item in plan.days[0].attractions]

    removed = trim_days_to_load(plan)

    assert removed == []
    assert [item.name for item in plan.days[0].attractions] == before


def test_trim_never_empties_a_day() -> None:
    """One stop is always better than an empty day, even if it is a heavy one."""
    plan = build_plan(day(attraction("国博", "博物馆")))

    removed = trim_days_to_load(plan)

    assert removed == []
    assert len(plan.days[0].attractions) == 1
