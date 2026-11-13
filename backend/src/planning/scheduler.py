"""Deterministic itinerary geometry: ordering, day splitting and load limits.

This module never talks to a model. It is the part that must be *correct*: a
day's stops are ordered by distance, days are filled with geographically
coherent stops, and no day is packed beyond what a person can walk.
"""

import math

from src.model.schemas import Attraction, Location

EARTH_RADIUS_METERS = 6_371_000.0
MAX_ATTRACTIONS_PER_DAY = 3


def haversine_meters(origin: Location | None, destination: Location | None) -> float:
    if origin is None or destination is None:
        return math.inf
    lon_delta = math.radians(destination.longitude - origin.longitude)
    lat_delta = math.radians(destination.latitude - origin.latitude)
    a = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(math.radians(origin.latitude))
        * math.cos(math.radians(destination.latitude))
        * math.sin(lon_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(a))


def order_by_nearest_neighbour(anchor: Location | None, items: list[Attraction]) -> list[Attraction]:
    """Greedy nearest-neighbour tour starting from ``anchor`` (usually the hotel)."""
    remaining = list(items)
    ordered: list[Attraction] = []
    current = anchor
    while remaining:
        index = min(
            range(len(remaining)),
            key=lambda i: (haversine_meters(current, remaining[i].location), remaining[i].name),
        )
        item = remaining.pop(index)
        ordered.append(item)
        current = item.location
    return ordered


def route_distance(anchor: Location | None, items: list[Attraction]) -> float:
    total = 0.0
    current = anchor
    for item in items:
        total += haversine_meters(current, item.location)
        current = item.location
    return total


def optimise_order(
    anchor: Location | None,
    items: list[Attraction],
    min_gain_ratio: float = 0.25,
) -> list[Attraction]:
    """Reorder only when it saves a meaningful amount of travel.

    Keeping the model's order matters when it encodes a plan ("morning museum,
    sunset viewpoint"); rewriting it for a 200 m gain is not worth losing that.
    """
    if len(items) < 3:
        return items
    current = route_distance(anchor, items)
    candidate = order_by_nearest_neighbour(anchor, items)
    improved = route_distance(anchor, candidate)
    if improved < current * (1 - min_gain_ratio):
        return candidate
    return items


def build_days(
    attractions: list[Attraction],
    days: int,
    anchor: Location | None,
    max_per_day: int = MAX_ATTRACTIONS_PER_DAY,
) -> list[list[Attraction]]:
    """Split attractions into ``days`` contiguous chunks of a nearest-neighbour tour.

    Because consecutive stops in the tour are close to each other, each chunk is
    a geographically coherent day rather than a slice of an arbitrary list.
    """
    seen: set[str] = set()
    unique: list[Attraction] = []
    for attraction in attractions:
        key = f"{attraction.name}|{attraction.address}".strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(attraction)

    ordered = order_by_nearest_neighbour(anchor, unique)
    total = len(ordered)
    groups: list[list[Attraction]] = []
    cursor = 0
    for day_index in range(days):
        remaining_days = days - day_index
        remaining = total - cursor
        if remaining <= 0:
            groups.append([])
            continue
        size = max(1, min(max_per_day, math.ceil(remaining / remaining_days)))
        groups.append(ordered[cursor : cursor + size])
        cursor += size

    # Anything left over (more candidates than 3 per day) goes to a day that
    # still has capacity; never overload a day past the limit.
    if cursor < total:
        for attraction in ordered[cursor:]:
            open_days = [index for index in range(days) if len(groups[index]) < max_per_day]
            if not open_days:
                break
            target = min(
                open_days,
                key=lambda index: haversine_meters(
                    attraction.location,
                    groups[index][-1].location if groups[index] else anchor,
                ),
            )
            groups[target].append(attraction)
    return groups


def enforce_load(
    groups: list[list[Attraction]],
    load_of,
    max_load: float | list[float],
    max_per_day: int = MAX_ATTRACTIONS_PER_DAY,
) -> list[list[Attraction]]:
    """Move or drop stops until each day fits the load budget.

    ``max_load`` may be one number or one per day: a late arrival or an early
    departure makes that day shorter, and the rule planner has to honour the same
    capacity the critic will measure it against.

    Used by the deterministic planner: a fallback plan should not claim that
    three museums fit in one day.
    """
    capacities = max_load if isinstance(max_load, list) else [max_load] * len(groups)

    def capacity_of(index: int) -> float:
        return capacities[index] if index < len(capacities) else capacities[-1]

    overflow: list[Attraction] = []
    for index, group in enumerate(groups):
        while len(group) > 1 and sum(load_of(item) for item in group) > capacity_of(index):
            overflow.append(group.pop())

    for item in overflow:
        candidates = [
            index
            for index, group in enumerate(groups)
            if len(group) < max_per_day
            and sum(load_of(existing) for existing in group) + load_of(item) <= capacity_of(index)
        ]
        if not candidates:
            continue
        target = min(
            candidates,
            key=lambda index: sum(load_of(existing) for existing in groups[index]),
        )
        groups[target].append(item)
    return groups
