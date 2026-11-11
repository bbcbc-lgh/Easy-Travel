"""Objective metrics for evaluating generated itineraries.

Everything here is deterministic: no model calls, no network. That is what makes
these numbers usable as a regression baseline — a prompt or scheduler change
either improves them or it does not.
"""

from dataclasses import asdict, dataclass

from src.model.schemas import TripPlan, TripPlanRequest
from src.planning.scheduler import MEAL_COST_CAP, haversine_meters

HOTEL_NIGHTLY = {"青年旅舍": 120, "经济型酒店": 280, "舒适型酒店": 520, "高端酒店": 980}
TRANSPORT_DAILY = {"公共交通": 45, "打车": 120, "自驾": 180}

PREFERENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "历史文化": ("博物馆", "故居", "遗址", "古镇", "古街", "寺", "塔", "纪念馆", "文化", "版本馆", "运河"),
    "自然风光": ("公园", "山", "湖", "湿地", "风景", "植物园", "溪", "岛", "森林"),
    "美食": ("餐厅", "小吃", "美食", "食", "茶", "菜"),
    "购物": ("购物", "商场", "市集", "市场", "商圈"),
    "艺术": ("美术馆", "艺术", "展览", "剧场", "音乐"),
    "休闲": ("公园", "茶", "咖啡", "慢行", "休闲", "广场"),
    "亲子": ("动物园", "科技馆", "乐园", "海洋馆", "亲子"),
    "摄影": ("观景", "塔", "日落", "夜景", "湖", "桥"),
}


@dataclass(slots=True)
class CaseMetrics:
    case_id: str
    days: int
    degraded: bool
    avg_intra_day_km: float
    max_intra_day_km: float
    duplicate_attractions: int
    day_structure_ok: bool
    meals_complete_rate: float
    cap_violations: int
    price_estimated: int
    price_unknown: int
    preference_hit_rate: float
    hours_known_rate: float
    budget_total: int
    reference_budget: int
    budget_deviation: float
    score: float

    def as_dict(self) -> dict:
        return asdict(self)


def intra_day_distances(plan: TripPlan) -> list[float]:
    """Metres travelled *between* a day's own stops (hotel legs excluded)."""
    distances: list[float] = []
    for day in plan.days:
        total = 0.0
        for previous, current in zip(day.attractions, day.attractions[1:]):
            total += haversine_meters(previous.location, current.location)
        distances.append(total)
    return distances


def duplicate_attractions(plan: TripPlan) -> int:
    names = [item.name for day in plan.days for item in day.attractions]
    return len(names) - len(set(names))


def day_structure_ok(plan: TripPlan, request: TripPlanRequest) -> bool:
    if len(plan.days) != request.days:
        return False
    for index, day in enumerate(plan.days):
        if day.day_index != index:
            return False
        if not 1 <= len(day.attractions) <= 3:
            return False
    return True


def meals_complete_rate(plan: TripPlan) -> float:
    days = [day for day in plan.days]
    if not days:
        return 0.0
    complete = sum(1 for day in days if len({meal.type for meal in day.meals}) >= 3)
    return complete / len(days)


def cap_violations(plan: TripPlan, request: TripPlanRequest) -> int:
    caps = MEAL_COST_CAP.get(request.budget, MEAL_COST_CAP["中等"])
    violations = 0
    for day in plan.days:
        for meal in day.meals:
            cap = caps.get(meal.type)
            if cap and meal.estimated_cost > cap:
                violations += 1
    return violations


def price_counts(plan: TripPlan) -> tuple[int, int]:
    items = [
        *[item for day in plan.days for item in day.attractions],
        *[item for day in plan.days for item in day.meals],
        *[day.hotel for day in plan.days if day.hotel],
    ]
    estimated = sum(1 for item in items if item.price_source == "estimated")
    unknown = sum(1 for item in items if item.price_source == "unknown")
    return estimated, unknown


def hours_known_rate(plan: TripPlan) -> float:
    """Share of venues whose opening hours came from the data provider."""
    items = [
        *[item for day in plan.days for item in day.attractions],
        *[item for day in plan.days for item in day.meals],
    ]
    if not items:
        return 0.0
    return sum(1 for item in items if item.opening_hours) / len(items)


def preference_hit_rate(plan: TripPlan, request: TripPlanRequest) -> float:
    attractions = [item for day in plan.days for item in day.attractions]
    if not attractions:
        return 0.0

    keywords: set[str] = set()
    for label in _split_preferences(request.preferences):
        if label in PREFERENCE_KEYWORDS:
            keywords.update(PREFERENCE_KEYWORDS[label])
        else:
            keywords.add(label)

    if not keywords:
        return 0.0

    hits = 0
    for item in attractions:
        haystack = f"{item.name}{item.category}{item.description}"
        if any(keyword and keyword in haystack for keyword in keywords):
            hits += 1
    return hits / len(attractions)


def reference_budget(request: TripPlanRequest) -> int:
    """What this trip should roughly cost if it actually respects the budget tier."""
    caps = MEAL_COST_CAP.get(request.budget, MEAL_COST_CAP["中等"])
    meals = 0.8 * (caps["breakfast"] + caps["lunch"] + caps["dinner"]) * request.days
    hotel = max(request.days - 1, 0) * HOTEL_NIGHTLY.get(request.accommodation, 280)
    transport = TRANSPORT_DAILY.get(request.transportation, 45) * request.days
    return round(meals + hotel + transport)


def budget_deviation(plan: TripPlan, request: TripPlanRequest) -> float:
    reference = reference_budget(request)
    if reference <= 0 or plan.budget is None:
        return 0.0
    return abs(plan.budget.total - reference) / reference


def composite_score(metrics: CaseMetrics, offline: bool = False) -> float:
    """0-100.

    When offline, every plan is produced by the deterministic planner, so the
    "was a model used" component is dropped and the remaining weights are
    renormalised; otherwise it would cap every score at 90 by construction.
    """
    geo = 1 / (1 + metrics.avg_intra_day_km / 10)
    constraint = (
        (1.0 if metrics.day_structure_ok else 0.0)
        + metrics.meals_complete_rate
        + (1 - min(metrics.cap_violations / 3, 1.0))
    ) / 3
    preference = metrics.preference_hit_rate
    budget = 1 / (1 + metrics.budget_deviation)

    if offline:
        total = 0.34 * geo + 0.28 * constraint + 0.22 * preference + 0.16 * budget
    else:
        model = 0.0 if metrics.degraded else 1.0
        total = 0.30 * geo + 0.25 * constraint + 0.20 * preference + 0.15 * budget + 0.10 * model
    return round(total * 100, 1)


def measure(case_id: str, plan: TripPlan, request: TripPlanRequest, offline: bool = False) -> CaseMetrics:
    distances = intra_day_distances(plan)
    estimated, unknown = price_counts(plan)
    metrics = CaseMetrics(
        case_id=case_id,
        days=len(plan.days),
        degraded=plan.degraded,
        avg_intra_day_km=round(sum(distances) / len(distances) / 1000, 2) if distances else 0.0,
        max_intra_day_km=round(max(distances) / 1000, 2) if distances else 0.0,
        duplicate_attractions=duplicate_attractions(plan),
        day_structure_ok=day_structure_ok(plan, request),
        meals_complete_rate=round(meals_complete_rate(plan), 2),
        cap_violations=cap_violations(plan, request),
        price_estimated=estimated,
        price_unknown=unknown,
        preference_hit_rate=round(preference_hit_rate(plan, request), 2),
        hours_known_rate=round(hours_known_rate(plan), 2),
        budget_total=plan.budget.total if plan.budget else 0,
        reference_budget=reference_budget(request),
        budget_deviation=round(budget_deviation(plan, request), 2),
        score=0.0,
    )
    metrics.score = composite_score(metrics, offline=offline)
    return metrics


def _split_preferences(preferences: str) -> list[str]:
    for separator in ("，", "、", ",", ";", "；"):
        preferences = preferences.replace(separator, "|")
    return [part.strip() for part in preferences.split("|") if part.strip()]
