from datetime import date

import pytest

from src.model.schemas import Attraction, Hotel, Location, Meal, TripPlanRequest
from src.planning.scheduler import (
    build_days,
    order_by_nearest_neighbour,
    optimise_order,
    pick_meals,
    route_distance,
)

HOTEL = Hotel(
    name="测试酒店",
    address="杭州市",
    location=Location(longitude=120.150, latitude=30.270),
    estimated_cost=300,
    price_source="estimated",
    source="amap",
)


def attraction(name: str, longitude: float, latitude: float) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=Location(longitude=longitude, latitude=latitude),
        visit_duration=90,
        source="amap",
    )


def request(**overrides) -> TripPlanRequest:
    payload = {
        "city": "杭州",
        "start_date": date(2026, 11, 20),
        "days": 3,
        "budget": "中等",
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
    }
    payload.update(overrides)
    return TripPlanRequest(**payload)


CLUSTER_A = [
    attraction("A1", 120.150, 30.270),
    attraction("A2", 120.152, 30.272),
    attraction("A3", 120.154, 30.274),
]
CLUSTER_B = [
    attraction("B1", 120.450, 30.550),
    attraction("B2", 120.452, 30.552),
    attraction("B3", 120.454, 30.554),
]
INTERLEAVED = [CLUSTER_A[0], CLUSTER_B[0], CLUSTER_A[1], CLUSTER_B[1], CLUSTER_A[2], CLUSTER_B[2]]


def test_nearest_neighbour_orders_by_distance() -> None:
    ordered = order_by_nearest_neighbour(HOTEL.location, [CLUSTER_B[0], CLUSTER_A[2], CLUSTER_A[0]])

    assert [item.name for item in ordered] == ["A1", "A3", "B1"]


def test_optimise_order_keeps_model_order_when_gain_is_small() -> None:
    items = [CLUSTER_A[0], CLUSTER_A[1], CLUSTER_A[2]]

    assert [item.name for item in optimise_order(HOTEL.location, items)] == ["A1", "A2", "A3"]


def test_optimise_order_fixes_a_zig_zag_day() -> None:
    items = [CLUSTER_A[0], CLUSTER_B[0], CLUSTER_A[1], CLUSTER_A[2]]

    optimised = optimise_order(HOTEL.location, items)

    assert [item.name for item in optimised] == ["A1", "A2", "A3", "B1"]


def intra_day_distance(group) -> float:
    """Travel between the stops of one day, excluding the hotel leg."""
    if len(group) < 2:
        return 0.0
    return route_distance(group[0].location, group[1:])


def test_build_days_halves_travel_compared_to_sequential_slices() -> None:
    # What the old fallback did: take the candidate list in order.
    sequential = [INTERLEAVED[index * 2 : index * 2 + 2] for index in range(3)]
    sequential_distance = sum(intra_day_distance(group) for group in sequential)

    grouped = build_days(INTERLEAVED, 3, HOTEL.location)
    grouped_distance = sum(intra_day_distance(group) for group in grouped)

    assert len(grouped) == 3
    assert sequential_distance > 0
    assert grouped_distance <= sequential_distance * 0.5


def test_build_days_covers_all_days_and_respects_maximum() -> None:
    groups = build_days(INTERLEAVED + [attraction("C1", 120.160, 30.280)], 3, HOTEL.location)

    assert len(groups) == 3
    assert all(len(group) <= 3 for group in groups)
    assert sum(len(group) for group in groups) == 7


def meal(name: str, cost: int, longitude: float, latitude: float, description: str = "") -> Meal:
    return Meal(
        type="lunch",
        name=name,
        address="杭州市",
        location=Location(longitude=longitude, latitude=latitude),
        description=description,
        estimated_cost=cost,
        price_source="estimated",
        source="amap",
    )


def test_pick_meals_rejects_expensive_breakfast() -> None:
    meals = [
        meal("牛New寿喜烧", 172, 120.1505, 30.2705),
        meal("巷口包子铺", 18, 120.1510, 30.2708),
        meal("奎元馆", 45, 120.1520, 30.2720),
        meal("新安土菜", 98, 120.1530, 30.2730),
    ]

    picked = pick_meals(meals, request(), HOTEL, [CLUSTER_A[0]], set())

    breakfast = next(item for item in picked if item.type == "breakfast")
    assert breakfast.name == "巷口包子铺"
    assert breakfast.estimated_cost <= 50


def test_pick_meals_keeps_barbecue_out_of_breakfast() -> None:
    meals = [
        meal("炭火烧肉", 40, 120.1502, 30.2702),
        meal("老字号早点", 25, 120.1600, 30.2800),
    ]

    picked = pick_meals(meals, request(), HOTEL, [], set())

    breakfast = next(item for item in picked if item.type == "breakfast")
    assert breakfast.name == "老字号早点"


def test_pick_meals_respects_budget_caps_for_lunch_and_dinner() -> None:
    meals = [
        meal("平价面馆", 30, 120.1500, 30.2700),
        meal("高档日料", 441, 120.1501, 30.2701),
        meal("家常菜", 70, 120.1502, 30.2702),
    ]

    picked = pick_meals(meals, request(budget="经济"), HOTEL, [CLUSTER_A[0]], set())

    assert picked
    assert all(item.estimated_cost <= 80 for item in picked)
    assert all(item.name != "高档日料" for item in picked)


def test_meals_are_not_reused_across_days() -> None:
    meals = [
        meal("早餐铺", 15, 120.1500, 30.2700),
        meal("面馆", 35, 120.1501, 30.2701),
        meal("小炒", 60, 120.1502, 30.2702),
        meal("粥店", 20, 120.1503, 30.2703),
        meal("饺子馆", 40, 120.1504, 30.2704),
        meal("烧烤摊", 55, 120.1505, 30.2705),
    ]
    used: set[str] = set()

    first = pick_meals(meals, request(), HOTEL, [CLUSTER_A[0]], used)
    second = pick_meals(meals, request(), HOTEL, [CLUSTER_A[1]], used)

    first_names = {item.name for item in first}
    second_names = {item.name for item in second}
    assert len(first_names) == 3
    assert len(second_names) == 3
    assert first_names.isdisjoint(second_names)
