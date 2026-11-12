import logging
from dataclasses import dataclass, field
from datetime import date

from src.model.schemas import DayPlan, TripPlan, TripPlanRequest
from src.planning.density import DAILY_LOAD_LIMIT, day_load, describe_load
from src.planning.hours import is_closed_on, weekday_name
from src.planning.scheduler import haversine_meters
from src.service.logging import log_event

logger = logging.getLogger(__name__)

DAY_TRAVEL_LIMIT_METERS = 20_000
DAILY_ATTRACTION_LIMIT_MINUTES = 420


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

            if day_load(day) > DAILY_LOAD_LIMIT:
                # An issue, not a note: the model chose these stops, so it can
                # choose fewer. Filed as a note it only warned the user; a live
                # eval run showed every model-built plan over-packing its days
                # (load 4.0-6.0 against a 3.5 limit) while the rule planner, which
                # enforces the limit, never does.
                critique.issues.append(
                    f"第 {label} 天安排了 {describe_load(day)}，按景点类型估算一天走不完，"
                    "请减掉一个景点或换成更轻的安排。"
                )

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
