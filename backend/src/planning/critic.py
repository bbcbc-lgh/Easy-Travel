import logging
from dataclasses import dataclass, field
from datetime import date

from src.model.schemas import DayPlan, TripPlan, TripPlanRequest
from src.planning.density import DAILY_LOAD_LIMIT, day_load, describe_load
from src.planning.hours import is_closed_on, weekday_name
from src.planning.scheduler import MEAL_COST_CAP, haversine_meters
from src.service.logging import log_event

logger = logging.getLogger(__name__)

DAY_TRAVEL_LIMIT_METERS = 20_000
DAILY_ATTRACTION_LIMIT_MINUTES = 420

MEAL_LABELS = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}


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
    round. Meal prices, for example, are chosen by the scheduler from whatever
    the data layer offers — asking the model to "pick a cheaper restaurant"
    cannot change them, so they become notes instead of a costly retry.
    """

    def review(self, request: TripPlanRequest, plan: TripPlan) -> Critique:
        caps = MEAL_COST_CAP.get(request.budget, MEAL_COST_CAP["中等"])
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

            for meal in day.meals:
                cap = caps.get(meal.type)
                if cap and meal.estimated_cost > cap:
                    label_text = MEAL_LABELS.get(meal.type, "餐饮")
                    critique.notes.append(
                        f"第 {label} 天{label_text}「{meal.name}」人均约 {meal.estimated_cost} 元，"
                        f"高于{request.budget}预算的参考上限 {cap} 元。"
                    )

            critique.notes.extend(self._closure_notes(day))

            if day_load(day) > DAILY_LOAD_LIMIT:
                critique.notes.append(
                    f"第 {label} 天安排了 {describe_load(day)}，按景点类型估算一天走不完，建议减掉一个或拆到次日。"
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
    def _closure_notes(day: DayPlan) -> list[str]:
        """Flag venues whose stated hours exclude this day's weekday."""
        try:
            weekday = date.fromisoformat(day.date).weekday()
        except ValueError:
            return []

        notes: list[str] = []
        for item in [*day.attractions, *day.meals]:
            if is_closed_on(item.opening_hours, weekday):
                notes.append(
                    f"第 {day.day_index + 1} 天（{weekday_name(weekday)}）「{item.name}」"
                    "的营业时间显示当天可能不开放，请出发前确认。"
                )
        return notes
