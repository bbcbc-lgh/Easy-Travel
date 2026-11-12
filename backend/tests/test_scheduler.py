from datetime import date

from src.model.schemas import Attraction, Hotel, Location, TripPlanRequest
from src.planning.scheduler import (
    build_days,
    optimise_order,
    order_by_nearest_neighbour,
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
