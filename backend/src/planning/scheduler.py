"""Deterministic itinerary geometry: ordering, day splitting and meal choice.

This module never talks to a model. It is the part that must be *correct*: a
day's stops are ordered by distance, days are filled with geographically
coherent stops, and meals respect both budget and walking distance.
"""

import math

from src.model.schemas import Attraction, Hotel, Location, Meal, TripPlanRequest

EARTH_RADIUS_METERS = 6_371_000.0
MAX_ATTRACTIONS_PER_DAY = 3

BREAKFAST_RADIUS_METERS = 1_500
MEAL_RADIUS_METERS = 3_000

MEAL_COST_CAP: dict[str, dict[str, int]] = {
    "经济": {"breakfast": 30, "lunch": 60, "dinner": 80},
    "中等": {"breakfast": 50, "lunch": 110, "dinner": 150},
    "舒适": {"breakfast": 80, "lunch": 200, "dinner": 280},
    "豪华": {"breakfast": 150, "lunch": 400, "dinner": 600},
}

# Venues that make no sense for breakfast; used to keep 烧肉/火锅 out of the morning.
NON_BREAKFAST_TERMS = (
    "烧肉",
    "烤肉",
    "火锅",
    "放题",
    "自助",
    "日料",
    "寿喜",
    "海鲜",
    "烧烤",
    "串",
    "酒吧",
    "酒馆",
    "夜市",
)

# Drinks and desserts are not a meal; keep them out of lunch/dinner when a real
# restaurant is available.
LIGHT_MEAL_TERMS = ("茶饮", "咖啡", "奶茶", "甜品", "果汁", "冰室")


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
    max_load: float,
    max_per_day: int = MAX_ATTRACTIONS_PER_DAY,
) -> list[list[Attraction]]:
    """Move or drop stops until each day fits the load budget.

    Used by the deterministic planner: a fallback plan should not claim that
    three museums fit in one day.
    """
    overflow: list[Attraction] = []
    for group in groups:
        while len(group) > 1 and sum(load_of(item) for item in group) > max_load:
            overflow.append(group.pop())

    for item in overflow:
        candidates = [
            group
            for group in groups
            if len(group) < max_per_day and sum(load_of(existing) for existing in group) + load_of(item) <= max_load
        ]
        if not candidates:
            continue
        min(candidates, key=lambda group: sum(load_of(existing) for existing in group)).append(item)
    return groups


def pick_meals(
    meals: list[Meal],
    request: TripPlanRequest,
    hotel: Hotel | None,
    day_attractions: list[Attraction],
    used_keys: set[str],
    preferred: list[str] | None = None,
) -> list[Meal]:
    """Choose breakfast/lunch/dinner for one day under cost and distance limits."""
    if not meals:
        return []

    caps = MEAL_COST_CAP.get(request.budget, MEAL_COST_CAP["中等"])
    hotel_location = hotel.location if hotel else None
    anchors = [
        ("breakfast", hotel_location, BREAKFAST_RADIUS_METERS, caps["breakfast"]),
        (
            "lunch",
            day_attractions[0].location if day_attractions else hotel_location,
            MEAL_RADIUS_METERS,
            caps["lunch"],
        ),
        (
            "dinner",
            day_attractions[-1].location if day_attractions else hotel_location,
            MEAL_RADIUS_METERS,
            caps["dinner"],
        ),
    ]

    picked: list[Meal] = []
    for meal_type, anchor, radius, cap in anchors:
        meal = _choose_meal(
            meals,
            meal_type=meal_type,
            anchor=anchor,
            radius=radius,
            cap=cap,
            used_keys=used_keys,
            preferred=preferred or [],
        )
        if meal is None:
            continue
        payload = meal.model_dump()
        payload["type"] = meal_type
        picked.append(Meal.model_validate(payload))
    return picked


def _choose_meal(
    meals: list[Meal],
    *,
    meal_type: str,
    anchor: Location | None,
    radius: float,
    cap: int,
    used_keys: set[str],
    preferred: list[str],
) -> Meal | None:
    def key(meal: Meal) -> str:
        return "".join(meal.name.split()).lower()

    usable = [meal for meal in meals if key(meal) not in used_keys] or list(meals)
    # Judged against the *full* candidate list: if the data contains coordinates,
    # an unlocated candidate must never win merely because the located ones were
    # already used by an earlier meal.
    has_located = any(meal.location is not None for meal in meals)
    if has_located and not any(meal.location is not None for meal in usable):
        usable = [meal for meal in meals if meal.location is not None]

    def acceptable(meal: Meal) -> bool:
        if meal.estimated_cost > cap:
            return False
        if meal.location is None:
            return not has_located
        if haversine_meters(anchor, meal.location) > radius:
            return False
        if meal_type == "breakfast" and _is_non_breakfast(meal):
            return False
        if meal_type in {"lunch", "dinner"} and _is_light_meal(meal):
            return False
        return True

    for name in preferred:
        wanted = "".join(name.split()).lower()
        for meal in usable:
            if key(meal) == wanted and acceptable(meal):
                used_keys.add(key(meal))
                return meal

    strict = [meal for meal in usable if acceptable(meal)]
    if strict:
        choice = min(strict, key=lambda meal: _meal_score(meal, anchor))
        used_keys.add(key(choice))
        return choice

    # Relax the walking distance a little, but never the budget cap and never
    # the "no barbecue for breakfast" rule: an empty slot is more honest than a
    # 441 yuan dinner on an economy budget.
    relaxed = [
        meal
        for meal in usable
        if meal.estimated_cost <= cap
        and (meal_type != "breakfast" or not _is_non_breakfast(meal))
        and (not has_located or meal.location is not None)
        and (meal.location is None or haversine_meters(anchor, meal.location) <= radius * 2)
    ]
    if not relaxed:
        # Last resort for lunch/dinner only: stay within twice the cap rather
        # than leaving the traveller without a restaurant. Breakfast is never
        # compromised — skipping it is better than a 172 yuan barbecue.
        if meal_type == "breakfast":
            return None
        located = [meal for meal in usable if meal.location is not None]
        affordable = [meal for meal in (located or usable) if meal.estimated_cost <= cap * 2]
        if not affordable:
            return None
        nearby = [
            meal
            for meal in affordable
            if meal.location is not None and haversine_meters(anchor, meal.location) <= radius * 2
        ]
        if not nearby:
            # Nothing cheap nearby: reusing an already-chosen nearby meal beats
            # sending the traveller 40 km for a cheaper one.
            reusable = [
                meal
                for meal in meals
                if meal.location is not None
                and key(meal) in used_keys
                and haversine_meters(anchor, meal.location) <= radius * 2
            ]
            nearby = reusable
        pool = nearby or affordable
        choice = min(pool, key=lambda meal: (meal.estimated_cost, _meal_score(meal, anchor)))
        used_keys.add(key(choice))
        return choice
    choice = min(relaxed, key=lambda meal: _meal_score(meal, anchor))
    used_keys.add(key(choice))
    return choice


def _meal_score(meal: Meal, anchor: Location | None) -> float:
    distance = haversine_meters(anchor, meal.location)
    if math.isinf(distance):
        distance = 5_000.0
    return distance + meal.estimated_cost * 3


def _is_non_breakfast(meal: Meal) -> bool:
    haystack = f"{meal.name}{meal.description or ''}"
    return any(term in haystack for term in NON_BREAKFAST_TERMS)


def _is_light_meal(meal: Meal) -> bool:
    haystack = f"{meal.name}{meal.description or ''}"
    return any(term in haystack for term in LIGHT_MEAL_TERMS)
