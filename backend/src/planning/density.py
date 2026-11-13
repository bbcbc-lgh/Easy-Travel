"""How much of a day a stop actually consumes.

Walking minutes are a poor proxy: a national museum and a city park can both be
"90 minutes" on paper while the museum eats a morning with queues and security.
This module gives each stop a *load* instead, and a day has a budget.

Classification is **category first**. AMap returns a semicolon hierarchy such as
``"科教文化服务;博物馆;博物馆"``; matching a *segment* of that is precise. The previous
version matched substrings of ``name + category`` with terms as short as a single
character, which read:

* ``少年宫`` (a children's hall) as ``宫`` -> a palace, load 2.0
* ``市文化宫`` as ``宫`` -> load 2.0
* ``中山路步行街`` as ``山`` -> load 1.0, never reaching the ``步行街`` term

Two such stops then summed to 4.0 against a hard limit of 3.5, and the planner
either paid for a replan or dropped a perfectly walkable stop. The name fallback
below is therefore ordered *light before medium*: a name that says "步行街" is
light even if it also contains "山".
"""

from src.model.schemas import Attraction, DayPlan, TripPlan

DAILY_LOAD_LIMIT = 3.5

#: An arrival after noon, or a departure before early afternoon, leaves half a day.
#: Treating day 1 and the last day like every other day is how a plan ends up
#: telling someone who lands at 16:00 to visit three museums.
HALF_DAY_LOAD = 2.0
SHORT_DAY_LOAD = 1.5
_LATE_ARRIVAL_MINUTE = 12 * 60
_EARLY_DEPARTURE_MINUTE = 14 * 60

HEAVY_LOAD = 2.0
MEDIUM_LOAD = 1.0
LIGHT_LOAD = 0.5
DEFAULT_LOAD = 1.0

#: AMap `type` segments that mean "you will spend a morning or an afternoon here".
HEAVY_SEGMENTS = frozenset(
    {
        "博物馆",
        "纪念馆",
        "美术馆",
        "展览馆",
        "科技馆",
        "水族馆",
        "天文馆",
        "海洋馆",
        "文物古迹",
        "遗址",
        "游乐场",
    }
)

#: Segments that mean "a normal stop".
MEDIUM_SEGMENTS = frozenset(
    {
        "风景名胜",
        "公园广场",
        "公园",
        "植物园",
        "动物园",
        "寺庙道观",
        "寺",
        "塔",
        "湖",
        "湿地",
        "广场",
        "海滨浴场",
        "自然保护区",
    }
)

#: Segments that mean "walk in, look around, leave".
LIGHT_SEGMENTS = frozenset(
    {
        "特色街区",
        "步行街",
        "商业街",
        "购物中心",
        "购物服务",
        "市集",
        "休闲广场",
        "商圈",
    }
)

#: Names that contain a heavy-looking morpheme but are not heavy venues. Checked
#: before every other name rule: "少年宫" must never be read as "宫".
LIGHT_NAME_OVERRIDES = ("少年宫", "青少年宫", "文化宫", "工人文化宫")

_HEAVY_TERMS = (
    "博物馆",
    "纪念馆",
    "美术馆",
    "展览馆",
    "科技馆",
    "水族馆",
    "天文馆",
    "海洋馆",
    "故宫",
    "行宫",
    "离宫",
    "遗址",
    "陵",
    "版本馆",
)

#: Checked *before* the medium terms on purpose (see the module docstring).
_LIGHT_TERMS = (
    "街区",
    "老街",
    "市集",
    "市场",
    "步行街",
    "商圈",
    "购物",
    "商业街",
    "巷",
)

_MEDIUM_TERMS = ("风景", "公园", "山", "湖", "湿地", "植物园", "动物园", "广场", "寺", "塔")

#: Terms that mean "you will be outside". Used by the weather rule: a rainy day
#: planned entirely outdoors deserves a warning, not a silent schedule.
_OUTDOOR_SEGMENTS = frozenset({"风景名胜", "公园广场", "公园", "植物园", "动物园", "海滨浴场", "自然保护区"})
_OUTDOOR_TERMS = ("公园", "湖", "山", "湿地", "植物园", "动物园", "广场", "步行街", "街区")


def is_outdoor(attraction: Attraction) -> bool | None:
    """Whether the stop is spent outside; ``None`` when the data cannot say.

    Only used to phrase a warning, so an unknown is kept unknown rather than
    guessed: telling someone "your rainy day is all outdoors" when half the stops
    are museums would be its own kind of wrong.
    """
    segments = {segment.strip() for segment in (attraction.category or "").split(";") if segment.strip()}
    if segments & HEAVY_SEGMENTS:
        return False
    if segments & _OUTDOOR_SEGMENTS:
        return True
    name = attraction.name
    if any(term in name for term in _HEAVY_TERMS):
        return False
    if any(term in name for term in _OUTDOOR_TERMS):
        return True
    return None


def _load_from_category(category: str) -> float | None:
    """Load implied by AMap's type hierarchy, or ``None`` when it says nothing."""
    if not category:
        return None
    segments = {segment.strip() for segment in category.split(";") if segment.strip()}
    if not segments:
        return None
    if segments & HEAVY_SEGMENTS:
        return HEAVY_LOAD
    if segments & LIGHT_SEGMENTS:
        return LIGHT_LOAD
    if segments & MEDIUM_SEGMENTS:
        return MEDIUM_LOAD
    return None


def _load_from_name(name: str) -> float:
    if any(term in name for term in LIGHT_NAME_OVERRIDES):
        return LIGHT_LOAD
    if any(term in name for term in _HEAVY_TERMS):
        return HEAVY_LOAD
    if any(term in name for term in _LIGHT_TERMS):
        return LIGHT_LOAD
    if any(term in name for term in _MEDIUM_TERMS):
        return MEDIUM_LOAD
    return DEFAULT_LOAD


def attraction_load(attraction: Attraction) -> float:
    """How much of a day this stop eats."""
    by_category = _load_from_category(attraction.category)
    if by_category is not None:
        return by_category
    return _load_from_name(f"{attraction.name}{attraction.category}")


def day_load(day: DayPlan) -> float:
    return round(sum(attraction_load(item) for item in day.attractions), 1)


def parse_clock(value: str | None) -> int | None:
    """``"15:30"`` -> 930 minutes past midnight; ``None`` when absent or unreadable."""
    if not value:
        return None
    try:
        hour, minute = value.split(":", 1)
        return int(hour) * 60 + int(minute)
    except ValueError:
        return None


def day_capacity(day_index: int, total_days: int, request) -> float:
    """How much of a day this one actually has, once travel is accounted for.

    ``DAILY_LOAD_LIMIT`` is the ceiling for a whole day. A first day that starts at
    15:00 and a last day that ends at noon are not whole days, and the critic, the
    trimmer and the eval all measure against this one function so they cannot
    drift apart.
    """
    capacity = DAILY_LOAD_LIMIT
    arrival = parse_clock(getattr(request, "arrival_time", None))
    departure = parse_clock(getattr(request, "departure_time", None))
    if total_days >= 1 and day_index == 0 and arrival is not None and arrival >= _LATE_ARRIVAL_MINUTE:
        capacity = min(capacity, HALF_DAY_LOAD)
    if total_days >= 1 and day_index == total_days - 1 and departure is not None:
        if departure <= _EARLY_DEPARTURE_MINUTE:
            capacity = min(capacity, SHORT_DAY_LOAD)
    return capacity


def capacities_for(total_days: int, request) -> list[float]:
    return [day_capacity(index, total_days, request) for index in range(total_days)]


def overflow_days(plan, request) -> list[tuple[int, float]]:
    """``(day_index, load)`` for days that exceed their own capacity."""
    total = len(plan.days)
    return [
        (day.day_index, load)
        for day in plan.days
        if (load := day_load(day)) > day_capacity(day.day_index, total, request)
    ]


def describe_load(day: DayPlan, capacity: float = DAILY_LOAD_LIMIT) -> str:
    names = "、".join(item.name for item in day.attractions)
    return f"{names}（约 {day_load(day):.1f} 个单位，单日建议上限 {capacity}）"


def trim_days_to_load(plan: TripPlan, request) -> tuple[list[str], set[int]]:
    """Drop the tail of an over-loaded day until it fits, and say what was dropped.

    The model decides *which* places; how many of them fit in a day is arithmetic,
    and this project does not trust the model with arithmetic. A live eval run
    showed model plans at 4.0-6.0 load against a 3.5 limit: asking for a replan
    fixed some of them and cost a model call, so the remaining excess is trimmed
    here instead. Never empties a day: one stop is always better than none.

    The limit is per day, not one global number: a late arrival or an early
    departure shrinks that day's budget (see :func:`day_capacity`).

    Returns the messages and the day indexes that lost a stop, so the caller can
    recalculate those days' routes instead of leaving legs that point at a stop
    the plan no longer contains.
    """
    removed: list[str] = []
    changed: set[int] = set()
    total = len(plan.days)
    for day in plan.days:
        capacity = day_capacity(day.day_index, total, request)
        while len(day.attractions) > 1 and day_load(day) > capacity:
            dropped = day.attractions.pop()
            changed.add(day.day_index)
            removed.append(f"第 {day.day_index + 1} 天已移除「{dropped.name}」（单日强度超出上限）")
    return removed, changed
