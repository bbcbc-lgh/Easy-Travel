"""Lodging must be charged per night actually spent, at that night's hotel."""

from datetime import date

from src.model.schemas import DayPlan, Hotel, TripPlanRequest
from src.planning.budget import calculate_budget


def request(days: int = 3, transportation: str = "公共交通") -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 11, 20),
        days=days,
        preferences="历史文化",
        budget="中等",
        transportation=transportation,
        accommodation="经济型酒店",
    )


def day(index: int, hotel: Hotel | None) -> DayPlan:
    return DayPlan(
        date=f"2026-11-{20 + index:02d}",
        day_index=index,
        description="城市漫步",
        transportation="公共交通",
        accommodation="经济型酒店",
        hotel=hotel,
    )


def hotel(name: str, cost: int) -> Hotel:
    return Hotel(name=name, address="杭州市", estimated_cost=cost, source="amap")


def test_lodging_sums_every_night_not_just_the_first_hotel() -> None:
    """Regression: the old code read `days[0].hotel` once, so a mid-trip hotel
    change (which the reviser can produce) under-reported the total."""
    days = [day(0, hotel("甲酒店", 300)), day(1, hotel("乙酒店", 500)), day(2, hotel("乙酒店", 500))]

    budget = calculate_budget(days, request(days=3))

    # Two nights: the last day has no overnight.
    assert budget.total_hotels == 800


def test_single_day_trip_has_no_lodging() -> None:
    budget = calculate_budget([day(0, hotel("甲酒店", 300))], request(days=1))

    assert budget.total_hotels == 0


def test_a_night_without_a_hotel_is_not_free() -> None:
    """An unknown price must not silently count as zero: fall back to the known one."""
    budget = calculate_budget([day(0, None), day(1, hotel("乙酒店", 400))], request(days=2))

    assert budget.total_hotels == 400


def test_transport_follows_the_chosen_mode() -> None:
    days = [day(0, None), day(1, None)]

    public = calculate_budget(days, request(days=2, transportation="公共交通"))
    taxi = calculate_budget(days, request(days=2, transportation="打车"))

    assert taxi.total_transportation > public.total_transportation


def test_total_is_the_sum_of_its_parts() -> None:
    budget = calculate_budget([day(0, hotel("甲酒店", 300)), day(1, None)], request(days=2))

    assert budget.total == (
        budget.total_attractions
        + budget.total_hotels
        + budget.total_meals
        + budget.total_transportation
    )
