from datetime import date

from src.model.schemas import Attraction, DayPlan, Hotel, Location, Meal, TripPlan, TripPlanRequest
from src.planning.critic import PlanCritic
from src.planning.hours import closed_weekdays, is_closed_on, weekday_name
from src.service.amap import AMapService


def test_weekday_range_marks_the_rest_as_closed() -> None:
    assert closed_weekdays("周一至周日 09:00-17:00") == set()
    assert closed_weekdays("周二至周日 09:00-16:30") == {0}
    assert closed_weekdays("周一至周五 09:00-18:00") == {5, 6}


def test_explicit_closure_is_detected() -> None:
    assert 0 in closed_weekdays("周二至周日 09:00-16:30，周一闭馆")
    assert closed_weekdays("每周一闭馆") == {0}
    assert closed_weekdays("周一休息") == {0}


def test_hours_without_weekdays_are_unknown() -> None:
    assert closed_weekdays("09:00-17:00") is None
    assert closed_weekdays(None) is None
    assert closed_weekdays("") is None


def test_is_closed_on_handles_unknown() -> None:
    assert is_closed_on(None, 0) is None
    assert is_closed_on("周一至周日 09:00-17:00", 0) is False
    assert is_closed_on("周二至周日 09:00-17:00", 0) is True


def test_weekday_name() -> None:
    assert weekday_name(0) == "周一"
    assert weekday_name(6) == "周日"


def test_amap_extracts_opening_hours() -> None:
    assert AMapService._opening_hours({"business": {"opentime_week": "周一至周日 09:00-17:00"}}) == (
        "周一至周日 09:00-17:00"
    )
    assert AMapService._opening_hours({"biz_ext": {"opentime_today": "09:00-17:00"}}) == "09:00-17:00"
    assert AMapService._opening_hours({}) is None


def build_plan(day_date: str, hours: str) -> TripPlan:
    attraction = Attraction(
        name="周一闭馆的博物馆",
        address="杭州市",
        location=Location(longitude=120.15, latitude=30.27),
        category="博物馆",
        opening_hours=hours,
        price_source="api",
        source="amap",
    )
    hotel = Hotel(name="酒店", address="杭州市", estimated_cost=300, source="amap")
    return TripPlan(
        city="杭州",
        start_date=day_date,
        end_date=day_date,
        days=[
            DayPlan(
                date=day_date,
                day_index=0,
                description="测试",
                transportation="公共交通",
                accommodation="经济型酒店",
                hotel=hotel,
                attractions=[attraction],
                meals=[
                    Meal(type="breakfast", name="早餐", address="杭州市", estimated_cost=20, source="amap"),
                    Meal(type="lunch", name="午餐", address="杭州市", estimated_cost=40, source="amap"),
                    Meal(type="dinner", name="晚餐", address="杭州市", estimated_cost=60, source="amap"),
                ],
            )
        ],
        overall_suggestions="测试",
    )


def request(day_date: str) -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date.fromisoformat(day_date),
        days=1,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def test_critic_notes_a_venue_closed_on_that_weekday() -> None:
    monday = "2026-11-23"  # a Monday
    plan = build_plan(monday, "周二至周日 09:00-16:30")

    critique = PlanCritic().review(request(monday), plan)

    assert critique.notes
    assert any("可能不开放" in note for note in critique.notes)


def test_critic_does_not_note_open_venues() -> None:
    monday = "2026-11-23"
    plan = build_plan(monday, "周一至周日 09:00-17:00")

    critique = PlanCritic().review(request(monday), plan)

    assert not any("可能不开放" in note for note in critique.notes)


def test_evals_count_opening_hours() -> None:
    from evals.metrics import hours_known_rate

    monday = "2026-11-23"
    with_hours = build_plan(monday, "周一至周日 09:00-17:00")
    without_hours = build_plan(monday, "")

    assert hours_known_rate(with_hours) > 0
    assert hours_known_rate(without_hours) == 0
