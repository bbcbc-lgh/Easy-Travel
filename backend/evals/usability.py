"""Can a traveller actually follow this plan?

The composite score answers "how good is this itinerary". This answers a narrower
question, and the one that matters for a tool whose job is to save the user the
research: if you printed the plan and walked out of the hotel, would it work?

Every rule below reuses the threshold the application itself enforces - the same
constants the critic reports on - so the eval cannot drift into measuring
something the product does not promise. Nothing here calls a model, so it costs
nothing to run on every push.
"""

from dataclasses import dataclass, field
from datetime import date

from src.model.schemas import DayPlan, TripPlan, TripPlanRequest
from src.planning.critic import DAILY_ATTRACTION_LIMIT_MINUTES, DAY_TRAVEL_LIMIT_METERS
from src.planning.density import DAILY_LOAD_LIMIT, day_load
from src.planning.hours import is_closed_on, weekday_name
from src.planning.scheduler import MEAL_COST_CAP, haversine_meters

MEAL_LABELS = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}
REQUIRED_MEALS = ("breakfast", "lunch", "dinner")


@dataclass(frozen=True, slots=True)
class Rule:
    key: str
    label: str


#: Ordered as a reader would walk through a plan: stops, then the day's shape,
#: then where you eat and sleep.
RULES: tuple[Rule, ...] = (
    Rule("days_have_stops", "每天都有景点"),
    Rule("day_travel", "单日景点间移动不超过 20 公里"),
    Rule("day_duration", "单日游览时长不超过 7 小时"),
    Rule("day_load", "单日强度不超过建议上限"),
    Rule("meals_complete", "每天三餐齐全"),
    Rule("meal_budget", "餐费不超过预算档位上限"),
    Rule("open_on_the_day", "当天没有闭馆地点"),
    Rule("no_duplicates", "没有重复景点"),
)

RULE_BY_KEY = {rule.key: rule for rule in RULES}


@dataclass(frozen=True, slots=True)
class Failure:
    rule: str
    message: str


@dataclass(slots=True)
class CaseUsability:
    case_id: str
    failures: list[Failure] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.failures


@dataclass(slots=True)
class UsabilitySummary:
    cases: int
    usable: int
    failures_by_rule: dict[str, int]
    unusable_cases: list[str]

    @property
    def usable_ratio(self) -> float:
        return self.usable / self.cases if self.cases else 0.0


def _intra_day_meters(day: DayPlan) -> float:
    return sum(
        haversine_meters(previous.location, current.location)
        for previous, current in zip(day.attractions, day.attractions[1:], strict=False)
    )


def _meal_cap(request: TripPlanRequest, meal_type: str) -> int | None:
    caps = MEAL_COST_CAP.get(request.budget, MEAL_COST_CAP["中等"])
    return caps.get(meal_type)


def assess(plan: TripPlan, request: TripPlanRequest, case_id: str) -> CaseUsability:
    """Every rule the plan breaks, in reading order. Empty list means usable."""
    case = CaseUsability(case_id=case_id)
    failures = case.failures

    for day in plan.days:
        label = day.day_index + 1
        if not day.attractions:
            failures.append(Failure("days_have_stops", f"第 {label} 天没有景点"))
            continue

        travel = _intra_day_meters(day)
        if travel > DAY_TRAVEL_LIMIT_METERS:
            failures.append(
                Failure(
                    "day_travel",
                    f"第 {label} 天景点间移动约 {travel / 1000:.0f} 公里（上限 {DAY_TRAVEL_LIMIT_METERS / 1000:.0f}）",
                )
            )

        duration = sum(item.visit_duration for item in day.attractions)
        if duration > DAILY_ATTRACTION_LIMIT_MINUTES:
            failures.append(
                Failure(
                    "day_duration",
                    f"第 {label} 天游览 {duration} 分钟（上限 {DAILY_ATTRACTION_LIMIT_MINUTES}）",
                )
            )

        load = day_load(day)
        if load > DAILY_LOAD_LIMIT:
            failures.append(Failure("day_load", f"第 {label} 天强度 {load:.1f}（上限 {DAILY_LOAD_LIMIT}）"))

        present = {meal.type for meal in day.meals}
        missing = [MEAL_LABELS[meal] for meal in REQUIRED_MEALS if meal not in present]
        if missing:
            failures.append(Failure("meals_complete", f"第 {label} 天缺少{'、'.join(missing)}"))

        for meal in day.meals:
            cap = _meal_cap(request, meal.type)
            if cap is not None and meal.estimated_cost > cap:
                failures.append(
                    Failure(
                        "meal_budget",
                        f"第 {label} 天{MEAL_LABELS.get(meal.type, '餐饮')}"
                        f"「{meal.name}」{meal.estimated_cost} 元（上限 {cap}）",
                    )
                )

        try:
            weekday = date.fromisoformat(day.date).weekday()
        except ValueError:
            continue
        for item in [*day.attractions, *day.meals]:
            if is_closed_on(item.opening_hours, weekday) is True:
                failures.append(
                    Failure(
                        "open_on_the_day",
                        f"第 {label} 天（{weekday_name(weekday)}）「{item.name}」当天显示不开放",
                    )
                )

    seen: set[str] = set()
    for day in plan.days:
        for attraction in day.attractions:
            key = f"{attraction.name}|{attraction.address}".strip().lower()
            if key in seen:
                failures.append(Failure("no_duplicates", f"「{attraction.name}」出现多次"))
            seen.add(key)

    return case


def summarise(results: list[CaseUsability]) -> UsabilitySummary:
    failures_by_rule: dict[str, int] = {rule.key: 0 for rule in RULES}
    unusable = []
    for result in results:
        if not result.usable:
            unusable.append(result.case_id)
        for failure in result.failures:
            failures_by_rule[failure.rule] = failures_by_rule.get(failure.rule, 0) + 1
    return UsabilitySummary(
        cases=len(results),
        usable=sum(1 for result in results if result.usable),
        failures_by_rule=failures_by_rule,
        unusable_cases=unusable,
    )
