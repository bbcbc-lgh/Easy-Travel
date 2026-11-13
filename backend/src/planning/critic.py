import logging
from dataclasses import dataclass, field
from datetime import date

from src.model.schemas import DayPlan, TripPlan, TripPlanRequest
from src.planning import must_visit
from src.planning.density import day_capacity, day_load, describe_load, is_outdoor
from src.planning.hours import is_closed_on, weekday_name
from src.planning.scheduler import haversine_meters
from src.service.logging import log_event

logger = logging.getLogger(__name__)

DAY_TRAVEL_LIMIT_METERS = 20_000
DAILY_ATTRACTION_LIMIT_MINUTES = 420

#: Weather that makes an outdoor day a bad idea.
_RAINY_TERMS = ("雨", "雪", "雷")


@dataclass(slots=True)
class Critique:
    """Separates what the model can fix from what only the data can fix."""

    issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def needs_revision(self) -> bool:
        return bool(self.issues)


def _intra_day_meters(day: DayPlan) -> float:
    """Travel between the day's stops, excluding the hotel leg.

    A day trip that starts with a 26 km ride to a distant site but then stays in
    one area is fine; a day that zig-zags between distant sites is not. Only the
    latter is what this measures.
    """
    total = 0.0
    for previous, current in zip(day.attractions, day.attractions[1:], strict=False):
        total += haversine_meters(previous.location, current.location)
    return total


class PlanCritic:
    """Deterministic critic that reports problems objectively.

    Only issues the model actually controls go back into the next planning
    round; anything the data layer decides becomes a note instead of a costly
    retry.
    """

    def review(self, request: TripPlanRequest, plan: TripPlan) -> Critique:
        critique = Critique()
        total_days = len(plan.days)
        weather_by_date = {item.date: item for item in plan.weather_info}

        for day in plan.days:
            label = day.day_index + 1
            if not day.attractions:
                critique.issues.append(f"第 {label} 天没有安排景点，请从候选景点中安排 1-3 个。")
                continue

            travel = _intra_day_meters(day)
            if travel > DAY_TRAVEL_LIMIT_METERS:
                critique.issues.append(
                    f"第 {label} 天景点间总移动约 {travel / 1000:.0f} 公里，跨度过大，请把当天景点集中到同一区域。"
                )

            if sum(item.visit_duration for item in day.attractions) > DAILY_ATTRACTION_LIMIT_MINUTES:
                critique.issues.append(f"第 {label} 天景点游览时间过长，请减少一个景点或换成更轻松的安排。")

            critique.issues.extend(self._closure_issues(day))

            named = _names_in_text(day)
            if named:
                # The description has to stay true after post-processing. It used to
                # name a stop that the load trim then dropped, leaving the day
                # describing a place it no longer contained.
                critique.issues.append(
                    f"第 {label} 天的说明里出现了具体场所名（{'、'.join(named)}），"
                    "说明只写活动类型、片区和节奏，不要提任何具体场所。"
                )

            capacity = day_capacity(day.day_index, total_days, request)
            if day_load(day) > capacity:
                # An issue, not a note: the model chose these stops, so it can
                # choose fewer. Filed as a note it only warned the user; a live
                # eval run showed every model-built plan over-packing its days
                # (load 4.0-6.0 against a 3.5 limit) while the rule planner, which
                # enforces the limit, never does.
                critique.issues.append(
                    f"第 {label} 天安排了 {describe_load(day, capacity)}，按景点类型估算一天走不完，"
                    "请减掉一个景点或换成更轻的安排。"
                )

        critique.issues.extend(self._must_visit_issues(request, plan))
        critique.notes.extend(self._weather_notes(plan, weather_by_date))

        if critique.issues or critique.notes:
            log_event(
                logger,
                "planner.critique",
                level=logging.INFO,
                issue_count=len(critique.issues),
                note_count=len(critique.notes),
                issues=critique.issues,
                notes=critique.notes,
            )
        return critique

    @staticmethod
    def _weather_notes(plan: TripPlan, weather_by_date: dict) -> list[str]:
        """A rainy day spent entirely outdoors, as a note rather than a retry.

        Not an issue on purpose: the model may not be able to fix it from the
        candidates it was given, and this project does not spend a paid replan on
        a hint. It still has to reach the user, because it changes what to pack.
        """
        notes: list[str] = []
        for day in plan.days:
            weather = weather_by_date.get(day.date)
            if weather is None or not day.attractions:
                continue
            if not any(term in (weather.day_weather or "") for term in _RAINY_TERMS):
                continue
            outdoors = [is_outdoor(item) for item in day.attractions]
            if any(value is True for value in outdoors) and not any(value is False for value in outdoors):
                notes.append(
                    f"第 {day.day_index + 1} 天预报{weather.day_weather}，当天安排的都是户外地点，"
                    "建议准备一个室内备选或调整顺序。"
                )
        return notes

    @staticmethod
    def _must_visit_issues(request: TripPlanRequest, plan: TripPlan) -> list[str]:
        """A place the traveller insists on must appear - exactly once.

        An issue rather than a note: the model can move a stop between days, so a
        missing or doubled must-visit is something it can fix in one retry.

        Skipped entirely for a degraded plan. The rule planner cannot look a place
        up, so on a sample-mode or fallback run this check can never be satisfied:
        it would spend one redundant replan and then tell the user to "please make
        sure it is scheduled", which is instruction they cannot act on. The data
        notice in :mod:`src.planning.notices` says what actually happened instead.
        """
        if not request.must_visit or plan.degraded:
            return []
        placed = [item.name for day in plan.days for item in day.attractions]
        issues = [
            f"必去地点「{name}」没有出现在行程里，请务必安排到某一天。"
            for name in must_visit.missing(request.must_visit, placed)
        ]
        for name in must_visit.duplicated(request.must_visit, placed):
            issues.append(f"必去地点「{name}」被安排了不止一次，同一处只去一次就够。")
        return issues

    @staticmethod
    def _closure_issues(day: DayPlan) -> list[str]:
        """Venues whose stated hours exclude this day's weekday.

        An issue rather than a note: moving the venue to another day, or choosing
        another one, is a decision the model can act on. `is_closed_on` returns
        True only when the opening-hours text says so, so uncertain data stays
        silent instead of triggering a retry.
        """
        try:
            weekday = date.fromisoformat(day.date).weekday()
        except ValueError:
            return []

        issues: list[str] = []
        for item in day.attractions:
            if is_closed_on(item.opening_hours, weekday) is True:
                issues.append(
                    f"第 {day.day_index + 1} 天（{weekday_name(weekday)}）「{item.name}」"
                    "营业时间显示当天不开放，请换到别的天或换成其他地点。"
                )
        return issues


def _names_in_text(day: DayPlan) -> list[str]:
    """Venue names from this day that appear in its description.

    Compared ignoring whitespace and with a two-character floor: a single character
    match would fire on any shared character, and short names like "鼓楼" are real
    places that should still count.
    """
    haystack = "".join(day.description.split())
    found: list[str] = []
    for item in day.attractions:
        key = "".join(item.name.split())
        if len(key) >= 2 and key in haystack and item.name not in found:
            found.append(item.name)
    hotel = day.hotel
    if hotel is not None:
        key = "".join(hotel.name.split())
        if len(key) >= 2 and key in haystack and hotel.name not in found:
            found.append(hotel.name)
    return found


def attach_critique(plan: TripPlan, critique: Critique, *, will_retry: bool) -> TripPlan:
    """Record the critic's findings on the plan so the user sees them.

    Notes are data limitations (a cheaper restaurant does not exist); they never
    justify another paid model round. Issues do justify one, and when no retry will
    happen — revisions exhausted, or a plan the user edited by hand — they are
    surfaced as warnings too. Dropping them silently would make a plan that cannot
    actually be walked look clean.
    """
    if plan.quality is None:
        return plan

    plan.quality.warnings.extend(critique.notes)
    if not will_retry:
        plan.quality.warnings.extend(f"未能自动修正：{issue}" for issue in critique.issues)
    return plan
