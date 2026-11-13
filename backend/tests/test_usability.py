"""Usability checks: can the plan be followed as written?

Each rule reuses a threshold the application enforces, so these tests also pin the
contract between the eval and the product: if someone relaxes DAY_TRAVEL_LIMIT_METERS
or DAILY_LOAD_LIMIT, the eval follows without a second edit.
"""

from datetime import date

from evals.usability import RULES, Failure, assess, summarise
from src.model.schemas import Attraction, DayPlan, Hotel, Location, TripPlan, TripPlanRequest
from src.planning.critic import DAILY_ATTRACTION_LIMIT_MINUTES, DAY_TRAVEL_LIMIT_METERS, PlanCritic
from src.planning.density import DAILY_LOAD_LIMIT

HANGZHOU = Location(longitude=120.15, latitude=30.27)


def request(budget: str = "中等", days: int = 2, **overrides) -> TripPlanRequest:
    payload = {
        "city": "杭州",
        "start_date": date(2026, 12, 1),
        "days": days,
        "preferences": "历史文化",
        "budget": budget,
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
    }
    payload.update(overrides)
    return TripPlanRequest(**payload)


def attraction(
    name: str = "景点",
    *,
    latitude: float = 30.27,
    visit_duration: int = 90,
    category: str = "风景名胜",
    opening_hours: str | None = None,
) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=Location(longitude=120.15, latitude=latitude),
        visit_duration=visit_duration,
        category=category,
        opening_hours=opening_hours,
        price_source="api",
        source="amap",
    )


def day(
    index: int = 0,
    *,
    attractions: list[Attraction] | None = None,
    when: str = "2026-12-01",
) -> DayPlan:
    return DayPlan(
        date=when,
        day_index=index,
        description="城市漫步",
        transportation="公共交通",
        accommodation="经济型酒店",
        hotel=Hotel(name="甲酒店", address="杭州市", estimated_cost=300, source="amap"),
        attractions=[attraction("景点A"), attraction("景点B")] if attractions is None else attractions,
    )


def trip(*days: DayPlan, request_: TripPlanRequest | None = None) -> TripPlan:
    plan = TripPlan(
        city="杭州",
        start_date="2026-12-01",
        end_date="2026-12-01",
        days=list(days) or [day()],
        overall_suggestions="出发前确认开放时间。",
    )
    return plan


def rules_broken(failures: list[Failure]) -> set[str]:
    return {failure.rule for failure in failures}


def test_a_reasonable_plan_is_usable() -> None:
    verdict = assess(trip(day()), request(), "ok")

    assert verdict.usable is True
    assert verdict.failures == []


def test_a_day_without_stops_is_unusable() -> None:
    verdict = assess(trip(day(attractions=[])), request(), "empty")

    assert verdict.usable is False
    assert "days_have_stops" in rules_broken(verdict.failures)


def test_a_zig_zag_day_breaks_the_travel_limit() -> None:
    # Roughly 30 km north of the first stop, well past the 20 km day limit.
    far = attraction("远郊景点", latitude=30.27 + 0.27)
    verdict = assess(trip(day(attractions=[attraction("市区景点"), far])), request(), "travel")

    assert "day_travel" in rules_broken(verdict.failures)
    assert DAY_TRAVEL_LIMIT_METERS == 20_000


def test_a_packed_day_breaks_duration_and_load() -> None:
    heavy = [attraction(f"博物馆{i}", category="博物馆", visit_duration=180) for i in range(3)]
    verdict = assess(trip(day(attractions=heavy)), request(), "packed")

    broken = rules_broken(verdict.failures)
    assert "day_duration" in broken
    assert "day_load" in broken
    assert sum(item.visit_duration for item in heavy) > DAILY_ATTRACTION_LIMIT_MINUTES
    assert DAILY_LOAD_LIMIT < 3 * 2.0


def test_a_closed_venue_is_unusable() -> None:
    # 2026-12-07 is a Monday.
    monday = day(attractions=[attraction("周一闭馆的馆", opening_hours="周一闭馆")], when="2026-12-07")
    verdict = assess(trip(monday), request(), "closed")

    assert "open_on_the_day" in rules_broken(verdict.failures)
    assert any("周一" in failure.message for failure in verdict.failures)


def test_a_venue_open_that_day_is_fine() -> None:
    monday = day(attractions=[attraction("正常开放", opening_hours="周一至周日 09:00-17:00")], when="2026-12-07")
    verdict = assess(trip(monday), request(), "open")

    assert "open_on_the_day" not in rules_broken(verdict.failures)


def test_a_weekday_only_venue_is_closed_on_the_weekend() -> None:
    """The same rule both ways: Tue-Sun is closed on Monday, so a Monday plan breaks."""
    monday = day(attractions=[attraction("周二到周日", opening_hours="周二至周日 09:00-17:00")], when="2026-12-07")
    verdict = assess(trip(monday), request(), "weekday-only")

    assert "open_on_the_day" in rules_broken(verdict.failures)


def test_a_repeated_stop_is_unusable() -> None:
    same = attraction("重复景点")
    verdict = assess(trip(day(attractions=[same, same.model_copy()])), request(), "dupes")

    assert "no_duplicates" in rules_broken(verdict.failures)


def test_every_rule_has_a_stable_key() -> None:
    """The keys end up in the report and in gate messages, so they are an API."""
    assert [rule.key for rule in RULES] == [
        "days_have_stops",
        "day_travel",
        "day_duration",
        "day_load",
        "open_on_the_day",
        "no_duplicates",
        "description_is_scoped",
    ]


def test_summary_counts_cases_and_failures_by_rule() -> None:
    results = [
        assess(trip(day()), request(), "good"),
        assess(trip(day(attractions=[])), request(), "no-stops"),
    ]

    summary = summarise(results)

    assert summary.cases == 2
    assert summary.usable == 1
    assert summary.usable_ratio == 0.5
    assert summary.unusable_cases == ["no-stops"]
    assert summary.failures_by_rule["days_have_stops"] == 1
    assert summary.failures_by_rule["day_travel"] == 0


def test_summary_of_nothing_is_zero_not_a_crash() -> None:
    summary = summarise([])

    assert summary.cases == 0
    assert summary.usable_ratio == 0.0


def test_a_description_naming_its_own_stop_is_fine() -> None:
    """Two-phase planning writes prose after trimming, so naming the stops is safe."""
    day_plan = day()
    day_plan.description = f"上午去{day_plan.attractions[0].name}，下午休息。"

    verdict = assess(trip(day_plan), request(), "named")

    assert verdict.usable is True


def test_a_description_naming_another_days_stop_is_unusable() -> None:
    """Prose that names another day's stop contradicts the route as soon as it moves."""
    first = day(0, attractions=[attraction("西湖")])
    second = day(1, attractions=[attraction("灵隐寺")], when="2026-12-02")
    second.description = "上午去西湖，下午休息。"

    verdict = assess(trip(first, second), request(), "cross-day")

    assert "description_is_scoped" in {f.rule for f in verdict.failures}


def test_a_longer_name_containing_another_days_name_is_not_a_leak() -> None:
    """Regression: "天安门广场" contains "天安门", which sat on another day.

    The substring hit failed a correct plan and would have replaced good prose.
    """
    first = day(0, attractions=[attraction("天安门广场")])
    first.description = "上午在天安门广场看升旗，午后休息。"
    second = day(1, attractions=[attraction("天安门")], when="2026-12-02")

    verdict = assess(trip(first, second), request(), "substring")

    assert "description_is_scoped" not in {f.rule for f in verdict.failures}


def test_a_description_about_pace_is_fine() -> None:
    day_plan = day()
    day_plan.description = "上午看展，午后散步，节奏轻松。"

    verdict = assess(trip(day_plan), request(), "pace")

    assert verdict.usable is True


def test_the_eval_and_the_product_agree_on_how_long_a_day_is() -> None:
    """Same rule, same numbers: a shortened day is short for the critic too.

    If these two ever measure against different limits, the eval stops describing
    the product and starts describing itself.
    """
    plan_day = day(
        attractions=[
            attraction("国博", category="科教文化服务;博物馆"),
            attraction("老街", category="购物服务;特色街区"),
        ]
    )

    def critic_flags(req) -> bool:
        critique = PlanCritic().review(req, trip(plan_day))
        return any("走不完" in issue for issue in critique.issues)

    def eval_flags(req) -> bool:
        verdict = assess(trip(plan_day), req, "capacity")
        return "day_load" in {failure.rule for failure in verdict.failures}

    relaxed = request()
    shortened = request(arrival_time="15:00")

    assert critic_flags(relaxed) is eval_flags(relaxed) is False
    assert critic_flags(shortened) is eval_flags(shortened) is True
