"""Compact, factual one-line descriptions of the candidate pool for a prompt.

The planner used to receive a bare list of names::

    候选景点：["西湖", "灵隐寺", "浙江省博物馆(孤山馆区)"]

With nothing but a name, the model cannot tell that two stops are 18 km apart,
that one is closed on the day it picked, or that three of them are heavy museums.
It therefore produced plans that broke exactly those constraints, and ``PlanCritic``
caught them and asked for a paid replan - spending an extra model call to repair
information the prompt had withheld in the first place.

Every fact here already exists on :class:`Attraction` / :class:`Hotel`; this module
only decides how to say it in one line. Two rules:

* an unknown never renders as a zero - "票价未知" is not "免费";
* nothing is invented. Opening hours come from the provider's text via
  :mod:`src.planning.hours`, which returns ``None`` when it cannot tell.
"""

import math

from src.model.schemas import Attraction, Hotel, Location
from src.planning.hours import closed_weekdays, weekday_name
from src.planning.must_visit import matches
from src.planning.scheduler import haversine_meters

#: How many stops a prompt may list. Every candidate costs roughly 40 tokens once
#: the facts are attached, so this is the knob that keeps the metadata affordable.
#: It was 24 with names only; 18 with facts measured +68% input tokens at 6
#: candidates, which is over the 40% budget the plan set.
MAX_PROMPT_ATTRACTIONS = 18
MAX_PROMPT_HOTELS = 6


def candidate_limit(days: int) -> int:
    """How many candidates to show for a trip of this length.

    18 is right for a weekend and starving for two weeks: with fewer candidates
    than days, the model has to repeat or invent a stop, and both are rejected.
    """
    return max(MAX_PROMPT_ATTRACTIONS, min(36, days * 2))


_UNKNOWN_HOURS = "开放时间未知"
_OPEN_DAILY = "每日开放"


def format_price(amount: int, source: str) -> str:
    """Say where the number came from; never turn an unknown price into zero."""
    if source == "unknown":
        return "票价未知"
    if amount <= 0:
        return "免费"
    prefix = "约" if source == "estimated" else ""
    return f"{prefix}{amount}元"


def format_nightly(hotel: Hotel) -> str:
    """Hotel price, in the same provenance-aware shape as tickets."""
    if hotel.price_source == "unknown" or hotel.estimated_cost <= 0:
        return "房价未知"
    prefix = "约" if hotel.price_source == "estimated" else ""
    return f"{prefix}{hotel.estimated_cost}元/晚"


def format_closed_days(opening_hours: str | None) -> str:
    """``周一、周三闭馆`` / ``每日开放`` / ``开放时间未知``.

    "Cannot tell" is its own answer and is spelled out: a venue whose hours we do
    not know is a risk the model should see, not a venue we silently call open.
    """
    closed = closed_weekdays(opening_hours)
    if closed is None:
        return _UNKNOWN_HOURS
    if not closed:
        return _OPEN_DAILY
    return f"{'、'.join(weekday_name(day) for day in sorted(closed))}闭馆"


def format_distance(meters: float) -> str:
    if math.isinf(meters):
        return "位置未知"
    if meters >= 1000:
        return f"{meters / 1000:.1f}km"
    return f"{max(meters, 0):.0f}m"


def short_category(category: str) -> str:
    """AMap's ``type`` is a semicolon hierarchy; the last segment is the specific one.

    ``"风景名胜;公园广场;公园"`` -> ``"公园"``. A sample record's plain label
    (``"历史文化"``) passes through unchanged.
    """
    segments = [segment.strip() for segment in (category or "").split(";") if segment.strip()]
    if not segments:
        return "景点"
    return segments[-1][:12]


def describe_attraction(attraction: Attraction, anchor: Location | None) -> str:
    """One line, pipe-separated: name | type | price | duration | hours | distance."""
    parts = [
        attraction.name,
        short_category(attraction.category),
        format_price(attraction.ticket_price, attraction.price_source),
        f"{attraction.visit_duration}分钟",
        format_closed_days(attraction.opening_hours),
        format_distance(haversine_meters(anchor, attraction.location)),
    ]
    return " | ".join(parts)


def describe_hotel(hotel: Hotel, anchor: Location | None) -> str:
    parts = [
        hotel.name,
        short_category(hotel.type or hotel.rating),
        format_nightly(hotel),
        format_distance(haversine_meters(anchor, hotel.location)),
    ]
    return " | ".join(parts)


def select_diverse(
    attractions: list[Attraction],
    limit: int,
    pinned: tuple[str, ...] | list[str] = (),
) -> list[Attraction]:
    """Take ``limit`` candidates while keeping the venue types mixed.

    Truncating the list would cut whatever the provider happened to return last,
    which is usually more of the same keyword's results. Round-robin by type
    instead, so a trimmed pool still contains a museum *and* a park *and* a street
    when it can - the model can only build a varied trip from a varied list.

    ``pinned`` names (the user's must-visit places) are always included first: a
    place the traveller asked for cannot be cut by a budget rule.
    """
    kept_pinned = [item for item in attractions if any(matches(query, item.name) for query in pinned)][:limit]
    pinned_ids = {id(item) for item in kept_pinned}
    rest = [item for item in attractions if id(item) not in pinned_ids]

    if len(kept_pinned) + len(rest) <= limit:
        return kept_pinned + rest

    buckets: dict[str, list[Attraction]] = {}
    for item in rest:
        buckets.setdefault(short_category(item.category), []).append(item)

    picked: list[Attraction] = []
    cursors = dict.fromkeys(buckets, 0)
    while len(picked) < limit - len(kept_pinned):
        progressed = False
        for key, bucket in buckets.items():
            index = cursors[key]
            if index < len(bucket):
                picked.append(bucket[index])
                cursors[key] = index + 1
                progressed = True
                if len(picked) >= limit - len(kept_pinned):
                    break
        if not progressed:
            break
    return kept_pinned + picked


def attraction_lines(
    attractions: list[Attraction],
    anchor: Location | None,
    limit: int = MAX_PROMPT_ATTRACTIONS,
    pinned: tuple[str, ...] | list[str] = (),
) -> list[str]:
    return [describe_attraction(item, anchor) for item in select_diverse(attractions, limit, pinned=pinned)]


def hotel_lines(
    hotels: list[Hotel],
    anchor: Location | None,
    limit: int = MAX_PROMPT_HOTELS,
) -> list[str]:
    return [describe_hotel(item, anchor) for item in hotels[:limit]]


def anchor_location(hotels: list[Hotel]) -> Location | None:
    """The location distances are measured from: the hotel the plan will default to.

    ``LLMPlanner._hydrate`` falls back to the first candidate hotel, so the prompt
    must measure from the same place or the numbers it reads would be about a
    different base than the plan gets built on.
    """
    for hotel in hotels:
        if hotel.location is not None:
            return hotel.location
    return None
