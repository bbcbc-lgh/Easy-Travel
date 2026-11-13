"""Give a day a clock.

A list of stops without times is not an itinerary: it does not tell you whether
the museum closes before you get there, or that the last two stops are two hours
of walking when you have one. This module turns a day into start/end slots and,
where the provider states an opening window, keeps the slot inside it.

Hard rule: **never invent an opening time.** When ``opening_hours`` carries no
clock range, the stop is scheduled with a default duration and nothing is claimed
about when it is open. A plausible-looking timetable that is wrong is worse than
none, because people plan around it.
"""

from dataclasses import dataclass

from src.model.schemas import Attraction, DayPlan, TimelineSlot
from src.planning.hours import open_windows

#: No route data means a guess; 20 minutes is a short hop in a Chinese city.
DEFAULT_HOP_MINUTES = 20
#: A day starts at 09:00 unless the caller says otherwise.
DEFAULT_START_MINUTE = 9 * 60


@dataclass(frozen=True, slots=True)
class _Stop:
    attraction: Attraction
    window: tuple[int, int] | None


def _format(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _hops(day: DayPlan, count: int) -> list[int]:
    """Minutes between consecutive stops: the enriched routes when they line up."""
    durations = [leg.duration_minutes for leg in day.routes]
    if len(durations) == count:
        return [max(value, 1) for value in durations]
    return [DEFAULT_HOP_MINUTES] * count


def _stops(day: DayPlan) -> list[_Stop]:
    return [_Stop(item, _window(item.opening_hours)) for item in day.attractions]


def _window(text: str | None) -> tuple[int, int] | None:
    windows = open_windows(text)
    if not windows:
        return None
    return windows[0]


def _violations(stops: list[_Stop], day: DayPlan, start_minute: int) -> int:
    """How many stops the clock cannot accommodate inside their stated window."""
    cursor = start_minute
    hops = _hops(day, max(len(stops) - 1, 0))
    count = 0
    for index, stop in enumerate(stops):
        if index > 0:
            cursor += hops[index - 1] if index - 1 < len(hops) else DEFAULT_HOP_MINUTES
        started = cursor
        finished = started + stop.attraction.visit_duration
        if stop.window is not None:
            opens, closes = stop.window
            if started < opens or finished > closes:
                count += 1
        cursor = finished
    return count


def reorder_for_windows(day: DayPlan, start_minute: int = DEFAULT_START_MINUTE) -> tuple[list[Attraction], list[str]]:
    """Keep the model's order unless a different one fits the opening hours better.

    Two candidate orders are compared: the one the plan already has, and
    earliest-closing-first. The original wins ties, because a model's ordering
    often encodes intent ("museum in the morning, sunset viewpoint at the end")
    and should not be rewritten for a marginal gain.

    Returns the chosen order and any stop that still cannot be placed.
    """
    original = [item for item in day.attractions]
    if len(original) < 2:
        return original, _remaining_warnings(day, original, start_minute)

    base = _violations(_stops(day), day, start_minute)
    if base == 0:
        return original, []

    # Earliest deadline first; anything without a stated window goes last.
    ordered = sorted(
        original,
        key=lambda item: (_window(item.opening_hours) or (24 * 60, 24 * 60))[1],
    )
    candidate_day = day.model_copy(update={"attractions": ordered})
    if _violations(_stops(candidate_day), candidate_day, start_minute) < base:
        return ordered, _remaining_warnings(candidate_day, ordered, start_minute)

    return original, _remaining_warnings(day, original, start_minute)


def _remaining_warnings(day: DayPlan, attractions: list[Attraction], start_minute: int) -> list[str]:
    probe = day.model_copy(update={"attractions": attractions})
    cursor = start_minute
    hops = _hops(probe, max(len(attractions) - 1, 0))
    warnings: list[str] = []
    for index, item in enumerate(attractions):
        if index > 0:
            cursor += hops[index - 1] if index - 1 < len(hops) else DEFAULT_HOP_MINUTES
        finished = cursor + item.visit_duration
        window = _window(item.opening_hours)
        if window is not None:
            opens, closes = window
            if finished > closes:
                warnings.append(
                    f"「{item.name}」按当前顺序 {_format(cursor)} 开始、{_format(finished)} 结束，"
                    f"已经超过它 {_format(closes)} 的关门时间"
                )
            elif cursor < opens:
                warnings.append(f"「{item.name}」{_format(opens)} 才开放，之前的时间需要另作安排")
        cursor = finished
    return warnings


def build_timeline(day: DayPlan, start_minute: int = DEFAULT_START_MINUTE) -> list[TimelineSlot]:
    """Start/end slots for a day whose stop order is already decided."""
    slots: list[TimelineSlot] = []
    cursor = start_minute
    hops = _hops(day, max(len(day.attractions) - 1, 0))
    for index, item in enumerate(day.attractions):
        if index > 0:
            cursor += hops[index - 1] if index - 1 < len(hops) else DEFAULT_HOP_MINUTES
        started = cursor
        cursor = started + item.visit_duration
        slots.append(TimelineSlot(start=_format(started), end=_format(cursor), name=item.name))
    return slots


def schedule_day(day: DayPlan, start_minute: int = DEFAULT_START_MINUTE) -> tuple[DayPlan, list[str]]:
    """Apply ordering and attach the timeline, returning any clock warnings."""
    ordered, warnings = reorder_for_windows(day, start_minute)
    if ordered != day.attractions:
        day.attractions = ordered
    day.timeline = build_timeline(day, start_minute)
    return day, warnings
