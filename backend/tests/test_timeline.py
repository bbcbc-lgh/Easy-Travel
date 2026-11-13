"""A day with times, or no times at all - never invented opening hours."""

from src.model.schemas import Attraction, DayPlan, Hotel, Location, RouteLeg
from src.planning.hours import open_windows
from src.planning.timeline import (
    DEFAULT_START_MINUTE,
    build_timeline,
    reorder_for_windows,
    schedule_day,
)

HANGZHOU = Location(longitude=120.155, latitude=30.274)


def attraction(name: str, *, duration: int = 90, hours: str | None = None) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=HANGZHOU,
        visit_duration=duration,
        category="风景名胜;公园广场;公园",
        opening_hours=hours,
        source="amap",
    )


def day(*attractions: Attraction, routes: list[RouteLeg] | None = None) -> DayPlan:
    return DayPlan(
        date="2026-12-01",
        day_index=0,
        description="测试",
        transportation="公共交通",
        accommodation="经济型酒店",
        hotel=Hotel(name="甲酒店", address="杭州市", location=HANGZHOU, estimated_cost=300, source="amap"),
        attractions=list(attractions),
        routes=routes or [],
    )


def test_opening_windows_read_a_clock_range() -> None:
    assert open_windows("09:00-17:00") == [(540, 1020)]
    assert open_windows("09:00-12:00，13:30-17:00") == [(540, 720), (810, 1020)]


def test_opening_windows_are_none_when_the_text_has_no_clock() -> None:
    """The common case for AMap; it must never be read as "open all day"."""
    assert open_windows("全年开放") is None
    assert open_windows("周一闭馆") is None
    assert open_windows(None) is None


def test_a_day_starts_at_nine_and_advances_by_duration_and_travel() -> None:
    slots = build_timeline(day(attraction("甲"), attraction("乙")))

    assert slots[0].start == "09:00"
    assert slots[0].end == "10:30"
    assert slots[1].start == "10:50"  # 90 minutes + a 20 minute hop
    assert slots[1].end == "12:20"


def test_route_durations_are_used_when_they_line_up() -> None:
    routes = [RouteLeg(origin="甲", destination="乙", distance_meters=1000, duration_minutes=35, mode="公共交通")]

    slots = build_timeline(day(attraction("甲"), attraction("乙"), routes=routes))

    assert slots[1].start == "11:05"


def test_a_mismatched_route_list_falls_back_to_the_default_hop() -> None:
    """One leg for two hops: the pair does not describe this day, so ignore it."""
    routes = [RouteLeg(origin="x", destination="y", duration_minutes=99, mode="公共交通")]

    slots = build_timeline(day(attraction("甲"), attraction("乙"), attraction("丙"), routes=routes))

    assert slots[1].start == "10:50"
    assert slots[2].start == "12:40"


def test_an_empty_day_has_an_empty_timeline() -> None:
    assert build_timeline(day()) == []


def test_a_custom_start_is_honoured() -> None:
    slots = build_timeline(day(attraction("甲")), start_minute=14 * 60)

    assert slots[0].start == "14:00"


def test_closing_time_reshapes_the_order_when_the_model_had_it_backwards() -> None:
    """The museum shuts at 11:00 and the plan visits it last: swap, don't warn."""
    museum = attraction("博物馆", duration=120, hours="09:00-11:00")
    park = attraction("公园", duration=60, hours="08:00-20:00")

    ordered, warnings = reorder_for_windows(day(park, museum))

    assert [item.name for item in ordered] == ["博物馆", "公园"]
    assert warnings == []


def test_the_models_order_is_kept_when_both_orders_fit() -> None:
    first = attraction("甲", hours="09:00-18:00")
    second = attraction("乙", hours="09:00-18:00")

    ordered, warnings = reorder_for_windows(day(first, second))

    assert [item.name for item in ordered] == ["甲", "乙"]
    assert warnings == []


def test_an_impossible_day_gets_a_warning_instead_of_a_crash() -> None:
    late = attraction("夜间景点", duration=180, hours="20:00-21:00")

    _ordered, warnings = reorder_for_windows(day(late))

    assert warnings
    assert "夜间景点" in warnings[0]


def test_a_closing_time_warning_reads_as_a_sentence_not_a_riddle() -> None:
    """ "arrives at 12:00, earlier than its 10:00 closing" said the opposite of the truth."""
    museum = attraction("X馆", duration=180, hours="09:00-10:00")

    _ordered, warnings = reorder_for_windows(day(museum))

    assert warnings
    assert "超过它 10:00 的关门时间" in warnings[0]
    assert "早于" not in warnings[0]


def test_unknown_opening_hours_produce_no_warning() -> None:
    """Silence, not a guess: the data cannot say when this place is open."""
    ordered, warnings = reorder_for_windows(day(attraction("某地")))

    assert [item.name for item in ordered] == ["某地"]
    assert warnings == []


def test_schedule_day_attaches_the_timeline() -> None:
    plan_day, warnings = schedule_day(day(attraction("甲")))

    assert warnings == []
    assert [slot.name for slot in plan_day.timeline] == ["甲"]
    assert plan_day.timeline[0].start == "09:00"


def test_the_default_start_is_nine() -> None:
    assert DEFAULT_START_MINUTE == 9 * 60
