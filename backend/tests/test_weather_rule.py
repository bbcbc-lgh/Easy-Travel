"""Rain changes what to pack - so it must reach the user, without costing a retry."""

from datetime import date

from src.model.schemas import Attraction, DayPlan, Location, TripPlan, TripPlanRequest, WeatherInfo
from src.planning.critic import PlanCritic
from src.planning.density import is_outdoor

HANGZHOU = Location(longitude=120.155, latitude=30.274)


def request() -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 12, 1),
        days=1,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def attraction(name: str, category: str) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=HANGZHOU,
        category=category,
        source="amap",
    )


def weather(text: str) -> WeatherInfo:
    return WeatherInfo(
        date="2026-12-01",
        day_weather=text,
        night_weather="多云",
        day_temp=18,
        night_temp=9,
        wind_direction="东风",
        wind_power="2级",
    )


def plan_with(attractions: list[Attraction], forecast: WeatherInfo) -> TripPlan:
    day = DayPlan(
        date="2026-12-01",
        day_index=0,
        description="测试",
        transportation="公共交通",
        accommodation="经济型酒店",
        attractions=attractions,
    )
    return TripPlan(
        city="杭州",
        start_date="2026-12-01",
        end_date="2026-12-01",
        days=[day],
        weather_info=[forecast],
        overall_suggestions="测试",
    )


def test_a_museum_is_indoor_and_a_park_is_outdoor() -> None:
    assert is_outdoor(attraction("浙江省博物馆", "科教文化服务;博物馆;博物馆")) is False
    assert is_outdoor(attraction("西湖", "风景名胜;公园广场;公园")) is True


def test_an_unknown_category_stays_unknown() -> None:
    assert is_outdoor(attraction("某某中心", "其他")) is None


def test_a_rainy_all_outdoor_day_produces_a_note() -> None:
    plan = plan_with([attraction("西湖", "风景名胜;公园广场;公园")], weather("小雨"))

    critique = PlanCritic().review(request(), plan)

    assert any("户外" in note for note in critique.notes)
    assert critique.issues == []
    assert critique.needs_revision is False, "a hint must not spend a paid replan"


def test_a_rainy_day_with_an_indoor_stop_produces_no_note() -> None:
    plan = plan_with(
        [
            attraction("西湖", "风景名胜;公园广场;公园"),
            attraction("浙江省博物馆", "科教文化服务;博物馆;博物馆"),
        ],
        weather("中雨"),
    )

    critique = PlanCritic().review(request(), plan)

    assert not any("户外" in note for note in critique.notes)


def test_a_sunny_all_outdoor_day_produces_no_note() -> None:
    plan = plan_with([attraction("西湖", "风景名胜;公园广场;公园")], weather("晴"))

    critique = PlanCritic().review(request(), plan)

    assert not any("户外" in note for note in critique.notes)


def test_snow_counts_as_rain_for_this_rule() -> None:
    plan = plan_with([attraction("西湖", "风景名胜;公园广场;公园")], weather("小雪"))

    critique = PlanCritic().review(request(), plan)

    assert any("户外" in note for note in critique.notes)


def test_unknown_weather_produces_no_note() -> None:
    forecast = weather("天气待定")
    forecast.forecast_available = False
    plan = plan_with([attraction("西湖", "风景名胜;公园广场;公园")], forecast)

    critique = PlanCritic().review(request(), plan)

    assert not any("户外" in note for note in critique.notes)
