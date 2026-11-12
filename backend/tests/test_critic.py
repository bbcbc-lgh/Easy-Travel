from datetime import date

from src.model.schemas import Attraction, DayPlan, Hotel, Location, Meal, TripPlan, TripPlanRequest
from src.planning.critic import DAY_TRAVEL_LIMIT_METERS, PlanCritic


def request(**overrides) -> TripPlanRequest:
    payload = {
        "city": "杭州",
        "start_date": date(2026, 11, 20),
        "days": 1,
        "budget": "中等",
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
    }
    payload.update(overrides)
    return TripPlanRequest(**payload)


def attraction(name: str, longitude: float = 120.15, latitude: float = 30.27, duration: int = 90) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=Location(longitude=longitude, latitude=latitude),
        visit_duration=duration,
        source="amap",
    )


def meal(name: str, cost: int, meal_type: str = "lunch") -> Meal:
    return Meal(
        type=meal_type,
        name=name,
        address="杭州市",
        location=Location(longitude=120.15, latitude=30.27),
        estimated_cost=cost,
        price_source="api",
        source="amap",
    )


def plan_with(meals: list[Meal], attractions: list[Attraction]) -> TripPlan:
    hotel = Hotel(name="酒店", address="杭州市", estimated_cost=300, source="amap")
    return TripPlan(
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
                hotel=hotel,
                attractions=attractions,
                meals=meals,
            )
        ],
        overall_suggestions="测试",
    )


def test_critic_flags_a_day_that_zig_zags_between_distant_sites() -> None:
    plan = plan_with(
        meals=[meal("面馆", 30)],
        attractions=[
            attraction("六和塔", 120.13, 30.20),
            attraction("国家版本馆", 120.02, 30.40),
            attraction("运河景区", 120.16, 30.32),
        ],
    )

    critique = PlanCritic().review(request(), plan)

    assert critique.needs_revision
    assert any("跨度" in issue for issue in critique.issues)
    # Sanity: the threshold is what makes this fail.
    assert DAY_TRAVEL_LIMIT_METERS < 60_000


def test_critic_accepts_a_distant_but_coherent_day_trip() -> None:
    # Hotel -> 良渚 is far, but the two sites are 3 km apart: that is a fine day.
    plan = plan_with(
        meals=[meal("面馆", 30)],
        attractions=[
            attraction("良渚古城", 120.00, 30.40),
            attraction("国家版本馆", 120.02, 30.41),
        ],
    )

    critique = PlanCritic().review(request(), plan)

    assert critique.needs_revision is False


def test_critic_flags_a_day_without_attractions() -> None:
    plan = plan_with(meals=[], attractions=[])

    critique = PlanCritic().review(request(), plan)

    assert any("没有安排景点" in issue for issue in critique.issues)


def test_critic_accepts_a_reasonable_day() -> None:
    plan = plan_with(
        meals=[meal("面馆", 35, "breakfast"), meal("小炒", 60, "lunch"), meal("家常菜", 80, "dinner")],
        attractions=[attraction("A"), attraction("B", 120.151, 30.271)],
    )

    critique = PlanCritic().review(request(), plan)

    assert critique.needs_revision is False
