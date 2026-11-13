from datetime import date

import pytest

from src.model.schemas import Attraction, DayPlan, Location, PlanQuality, TripPlan, TripPlanRequest
from src.planning.critic import PlanCritic, attach_critique
from src.planning.density import (
    DAILY_LOAD_LIMIT,
    HALF_DAY_LOAD,
    HEAVY_LOAD,
    LIGHT_LOAD,
    MEDIUM_LOAD,
    SHORT_DAY_LOAD,
    attraction_load,
    capacities_for,
    day_capacity,
    day_load,
    parse_clock,
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


def day(*attractions: Attraction, index: int = 0) -> DayPlan:
    return DayPlan(
        date="2026-11-23",
        day_index=index,
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


#: Real place names, with the *category AMap actually returns for them*. Every
#: row here is a case the old substring classifier got wrong or could have got
#: wrong; the four marked "regression" were verified by running the old code.
LOAD_FIXTURES = [
    # (category, name, expected load)
    ("科教文化服务;博物馆;博物馆", "浙江省博物馆(孤山馆区)", HEAVY_LOAD),
    ("科教文化服务;文化宫;文化宫", "北京市少年宫", LIGHT_LOAD),  # regression: was 2.0
    ("科教文化服务;文化宫", "市文化宫", LIGHT_LOAD),  # regression: was 2.0
    ("购物服务;特色商业街;步行街", "中山路步行街", LIGHT_LOAD),  # regression: was 1.0
    ("", "宽窄巷子", LIGHT_LOAD),  # regression: was 1.0
    ("风景名胜;公园广场;公园", "中山公园", MEDIUM_LOAD),
    ("风景名胜;风景名胜;风景名胜", "西湖", MEDIUM_LOAD),
    ("科教文化服务;博物馆", "故宫博物院", HEAVY_LOAD),
    ("风景名胜;寺庙道观;寺庙道观", "灵隐寺", MEDIUM_LOAD),
    ("购物服务;购物中心;购物中心", "南京路步行街", LIGHT_LOAD),
    ("科教文化服务;科技馆", "上海科技馆", HEAVY_LOAD),
    ("风景名胜;公园广场;广场", "人民广场", MEDIUM_LOAD),
    ("科教文化服务;图书馆", "上海图书馆", 1.0),
    ("购物服务;市集", "南锣鼓巷", LIGHT_LOAD),
    ("风景名胜;公园广场;公园", "岳麓山", MEDIUM_LOAD),
    ("科教文化服务;纪念馆", "侵华日军南京大屠杀遇难同胞纪念馆", HEAVY_LOAD),
    ("", "外滩", 1.0),
    ("", "北京故宫", HEAVY_LOAD),
    ("购物服务;商业街", "王府井大街", LIGHT_LOAD),
    ("风景名胜;公园广场;动物园", "成都大熊猫繁育研究基地", MEDIUM_LOAD),
]


@pytest.mark.parametrize(("category", "name", "expected"), LOAD_FIXTURES)
def test_load_fixtures_match_how_a_traveller_experiences_the_place(category, name, expected) -> None:
    assert attraction_load(attraction(name, category)) == expected


def test_category_wins_over_a_misleading_name() -> None:
    """A museum named "...少年宫博物馆" is still a museum: the type is authoritative."""
    assert attraction_load(attraction("少年宫博物馆", "科教文化服务;博物馆")) == HEAVY_LOAD


def test_the_two_light_halls_do_not_trigger_a_paid_replan_together() -> None:
    """The regression this classifier was rebuilt for.

    "少年宫" + "市文化宫" used to sum to 4.0 against a 3.5 limit: the critic asked
    for a replan and, when that did not help, a walkable stop was trimmed away.
    """
    plan_day = day(attraction("北京市少年宫", ""), attraction("市文化宫", ""))

    assert day_load(plan_day) == 1.0
    assert day_load(plan_day) <= DAILY_LOAD_LIMIT


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


def test_enforce_load_accepts_a_capacity_per_day() -> None:
    """A day shortened by a late arrival gets a smaller budget, not the global one."""
    museums = [attraction(f"博物馆{i}", "博物馆") for i in range(3)]

    groups = enforce_load([museums, []], attraction_load, [HALF_DAY_LOAD, DAILY_LOAD_LIMIT])

    # Two heavy stops cannot fit the 2.0 first day; the second day takes one of
    # the displaced ones, and the third has nowhere left to go.
    assert len(groups[0]) == 1
    assert len(groups[1]) == 1
    assert sum(attraction_load(item) for item in groups[0]) <= HALF_DAY_LOAD


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


def request(days: int = 1, **overrides) -> TripPlanRequest:
    payload = {
        "city": "杭州",
        "start_date": date(2026, 11, 23),
        "days": days,
        "budget": "中等",
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
    }
    payload.update(overrides)
    return TripPlanRequest(**payload)


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

    removed, _changed = trim_days_to_load(plan, request())

    assert day_load(plan.days[0]) <= DAILY_LOAD_LIMIT
    assert removed
    assert all("已移除" in message for message in removed)
    assert any("养心殿" in message for message in removed)


def test_trim_leaves_a_fitting_day_alone() -> None:
    plan = build_plan(day(attraction("公园", "公园"), attraction("街区", "步行街")))
    before = [item.name for item in plan.days[0].attractions]

    removed, _changed = trim_days_to_load(plan, request())

    assert removed == []
    assert [item.name for item in plan.days[0].attractions] == before


def test_trim_never_empties_a_day() -> None:
    """One stop is always better than an empty day, even if it is a heavy one."""
    plan = build_plan(day(attraction("国博", "博物馆")))

    removed, _changed = trim_days_to_load(plan, request())

    assert removed == []
    assert len(plan.days[0].attractions) == 1


# --- C2: arrival and departure shorten a day --------------------------------


def test_clock_times_are_parsed_or_ignored() -> None:
    assert parse_clock("09:30") == 570
    assert parse_clock("15:00") == 900
    assert parse_clock(None) is None
    assert parse_clock("") is None
    assert parse_clock("not a time") is None


def test_a_morning_arrival_keeps_a_full_day() -> None:
    assert day_capacity(0, 3, request(arrival_time="09:00")) == DAILY_LOAD_LIMIT


def test_an_afternoon_arrival_halves_the_first_day() -> None:
    assert day_capacity(0, 3, request(arrival_time="15:00")) == HALF_DAY_LOAD
    # Only the first day is shortened.
    assert day_capacity(1, 3, request(arrival_time="15:00")) == DAILY_LOAD_LIMIT


def test_an_early_departure_shortens_the_last_day_only() -> None:
    assert day_capacity(2, 3, request(departure_time="11:00")) == SHORT_DAY_LOAD
    assert day_capacity(1, 3, request(departure_time="11:00")) == DAILY_LOAD_LIMIT


def test_a_single_day_trip_with_both_bounds_gets_the_tighter_capacity() -> None:
    assert day_capacity(0, 1, request(departure_time="12:00")) == SHORT_DAY_LOAD


def test_a_late_departure_keeps_a_full_day() -> None:
    assert day_capacity(2, 3, request(departure_time="20:00")) == DAILY_LOAD_LIMIT


def test_capacities_cover_every_day() -> None:
    assert capacities_for(3, request(arrival_time="16:00", departure_time="10:00")) == [
        HALF_DAY_LOAD,
        DAILY_LOAD_LIMIT,
        SHORT_DAY_LOAD,
    ]


def test_the_critic_judges_the_shortened_day_by_its_own_capacity() -> None:
    """A museum plus a street is fine on a normal day and too much on an arrival day."""
    plan = build_plan(day(attraction("国博", "博物馆"), attraction("老街", "特色街区")))

    relaxed = PlanCritic().review(request(), plan)
    tight = PlanCritic().review(request(arrival_time="15:00"), plan)

    assert not any("走不完" in issue for issue in relaxed.issues)
    assert any("走不完" in issue for issue in tight.issues)


def test_trim_respects_the_shortened_capacity() -> None:
    plan = build_plan(day(attraction("国博", "博物馆"), attraction("老街", "特色街区")))

    removed, changed = trim_days_to_load(plan, request(arrival_time="15:00"))

    assert removed
    assert changed == {0}
    assert day_load(plan.days[0]) <= HALF_DAY_LOAD
