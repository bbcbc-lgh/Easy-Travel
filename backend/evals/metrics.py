"""Objective metrics for evaluating generated itineraries.

Everything here is deterministic: no model calls, no network. That is what makes
these numbers usable as a regression baseline — a prompt or scheduler change
either improves them or it does not.
"""

from dataclasses import asdict, dataclass

from src.model.schemas import TripPlan, TripPlanRequest
from src.planning.budget import DEFAULT_MEAL_ALLOWANCE, MEAL_ALLOWANCE_DAILY
from src.planning.scheduler import haversine_meters

HOTEL_NIGHTLY = {"青年旅舍": 120, "经济型酒店": 280, "舒适型酒店": 520, "高端酒店": 980}
# A plan budget includes attraction tickets, so the reference has to include them
# too - otherwise "budget deviation" measures a definition gap rather than real
# overspending, and drops every case by the same amount.
TICKET_ALLOWANCE_DAILY = 60
TRANSPORT_DAILY = {"公共交通": 45, "打车": 120, "自驾": 180}

#: Which preference axes a *venue type* belongs to.
#:
#: This is the second half of the ADR-6 fix. The metric used to match keywords
#: against ``name + category``, so a place called "博物馆奇妙夜主题乐园" scored as
#: 历史文化 no matter what it actually is - the same "the name looks like it"
#: defect that was removed from the preference metric for ``description``, still
#: living one field over.
#:
#: Keys are type segments as AMap actually returns them. ``src.cli.poi_types``
#: prints the real ones for a city, which is where these came from: the live data
#: uses ``|`` for multi-valued segments ("博物馆|风景名胜") and carries types the
#: first version of this table had never seen ("旅游景点", "商场", "世界遗产").
CATEGORY_AXES: dict[str, frozenset[str]] = {
    # AMap venue types
    "博物馆": frozenset({"历史文化", "艺术"}),
    "纪念馆": frozenset({"历史文化"}),
    "美术馆": frozenset({"艺术", "历史文化"}),
    "展览馆": frozenset({"艺术"}),
    "科技馆": frozenset({"亲子"}),
    "水族馆": frozenset({"亲子"}),
    "动物园": frozenset({"亲子", "自然风光"}),
    "游乐场": frozenset({"亲子"}),
    "文物古迹": frozenset({"历史文化"}),
    "寺庙道观": frozenset({"历史文化"}),
    "遗址": frozenset({"历史文化"}),
    "世界遗产": frozenset({"历史文化"}),
    "红色景区": frozenset({"历史文化"}),
    "风景名胜": frozenset({"自然风光"}),
    "风景名胜相关": frozenset({"自然风光"}),
    "公园广场": frozenset({"自然风光", "休闲"}),
    "公园": frozenset({"自然风光", "休闲"}),
    "植物园": frozenset({"自然风光"}),
    "湖": frozenset({"自然风光"}),
    "湿地": frozenset({"自然风光"}),
    "城市广场": frozenset({"休闲", "摄影"}),
    "观景台": frozenset({"摄影"}),
    "购物中心": frozenset({"购物"}),
    "商场": frozenset({"购物"}),
    "商业街": frozenset({"购物"}),
    "特色街区": frozenset({"购物", "休闲"}),
    "市集": frozenset({"购物", "美食"}),
    "美食街": frozenset({"美食"}),
    # Offline sample labels
    "历史文化": frozenset({"历史文化"}),
    "自然风光": frozenset({"自然风光"}),
    "城市漫游": frozenset({"休闲"}),
    "艺术展览": frozenset({"艺术"}),
    "城市地标": frozenset({"摄影"}),
    "美食购物": frozenset({"美食", "购物"}),
}

#: Axes no venue *type* can express. A trip built around one of these cannot be
#: scored on it, and the honest answer is "not measured", not 0%. Reported here so
#: the gap is documented rather than silently averaged into the score.
UNMEASURABLE_AXES: frozenset[str] = frozenset(
    {
        "摄影",  # AMap types a photo spot as 风景名胜/城市广场/观景台; intent is invisible
    }
)


@dataclass(slots=True)
class CaseMetrics:
    """One case's measurements.

    Every field but ``case_id`` defaults to "nothing measured". The runner builds
    a blank record for a case that failed to produce a plan, and that path used to
    enumerate all fields by hand - so adding a field here (``hours_known_rate`` was
    added that way) made the failure path raise ``TypeError`` instead of recording
    the failure. Defaults make that impossible.
    """

    case_id: str
    days: int = 0
    degraded: bool = False
    avg_intra_day_km: float = 0.0
    max_intra_day_km: float = 0.0
    duplicate_attractions: int = 0
    day_structure_ok: bool = False
    price_estimated: int = 0
    price_unknown: int = 0
    preference_hit_rate: float | None = None
    hours_known_rate: float = 0.0
    budget_total: int = 0
    reference_budget: int = 0
    budget_deviation: float = 0.0
    score: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def intra_day_distances(plan: TripPlan) -> list[float]:
    """Metres travelled *between* a day's own stops (hotel legs excluded)."""
    distances: list[float] = []
    for day in plan.days:
        total = 0.0
        for previous, current in zip(day.attractions, day.attractions[1:], strict=False):
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


def price_counts(plan: TripPlan) -> tuple[int, int]:
    items = [
        *[item for day in plan.days for item in day.attractions],
        *[day.hotel for day in plan.days if day.hotel],
    ]
    estimated = sum(1 for item in items if item.price_source == "estimated")
    unknown = sum(1 for item in items if item.price_source == "unknown")
    return estimated, unknown


def hours_known_rate(plan: TripPlan) -> float:
    """Share of venues whose opening hours came from the data provider."""
    items = [
        *[item for day in plan.days for item in day.attractions],
    ]
    if not items:
        return 0.0
    return sum(1 for item in items if item.opening_hours) / len(items)


def preference_hit_rate(plan: TripPlan, request: TripPlanRequest) -> float | None:
    """Share of stops whose *venue type* satisfies the requested preferences.

    Only ``category`` is inspected. ``name`` is deliberately excluded: it is a
    label, and scoring it rewards places that happen to be called "博物馆…" rather
    than places that are one. ``description`` was removed for the same reason in
    ADR-6; this closes the other half.

    Returns ``None`` - not ``0.0`` - when no stop carried a type that maps to any
    preference axis. That is a measurement failure ("this plan cannot be scored on
    preference"), and conflating it with "scored zero" would let the metric punish
    a whole class of trips: a photography itinerary is made of 风景名胜 and
    城市广场, and before this distinction every one of them read as 0%.
    """
    attractions = [item for day in plan.days for item in day.attractions]
    if not attractions:
        return None

    axes: set[str] = set()
    for label in _split_preferences(request.preferences):
        axes |= CATEGORY_AXES.get(label, frozenset({label}))

    if not axes:
        return None

    known = [_axes_for_category(item.category) for item in attractions]
    if not any(known):
        return None

    hits = sum(1 for item_axes in known if item_axes & axes)
    return hits / len(attractions)


def _axes_for_category(category: str) -> set[str]:
    """Preference axes implied by the venue's type.

    A segment may itself be multi-valued: AMap returns ``"博物馆|风景名胜"``, so
    splitting on ``;`` alone left whole attractions unmapped and silently scored 0.
    """
    found: set[str] = set()
    for group in (category or "").replace("|", ";").split(";"):
        key = group.strip()
        if key in CATEGORY_AXES:
            found |= set(CATEGORY_AXES[key])
    return found


def reference_budget(request: TripPlanRequest) -> int:
    """What this trip should roughly cost if it actually respects the budget tier."""
    allowance = MEAL_ALLOWANCE_DAILY.get(request.budget, DEFAULT_MEAL_ALLOWANCE)
    meals = allowance * request.days
    hotel = max(request.days - 1, 0) * HOTEL_NIGHTLY.get(request.accommodation, 280)
    transport = TRANSPORT_DAILY.get(request.transportation, 45) * request.days
    tickets = TICKET_ALLOWANCE_DAILY * request.days
    return round(meals + hotel + transport + tickets)


def budget_deviation(plan: TripPlan, request: TripPlanRequest) -> float:
    reference = reference_budget(request)
    if reference <= 0 or plan.budget is None:
        return 0.0
    return abs(plan.budget.total - reference) / reference


def composite_score(metrics: CaseMetrics, offline: bool = False) -> float:
    """0-100, renormalised over whatever was actually measured.

    Two components can be missing: "was a model used" (offline runs) and
    "preference fit" (plans whose venue types map to no preference axis). Dropping
    the weight and renormalising is the only honest option - scoring a missing
    component as 0 would make an unmeasurable trip look like a bad one.
    """
    geo = 1 / (1 + metrics.avg_intra_day_km / 10)
    constraint = (
        (1.0 if metrics.day_structure_ok else 0.0)
        # A repeated stop is a defect no amount of good geometry excuses, so it
        # must not be able to score full marks on the constraint axis.
        + (1.0 if metrics.duplicate_attractions == 0 else 0.0)
    ) / 2
    budget = 1 / (1 + metrics.budget_deviation)

    parts: list[tuple[float | None, float]] = [
        (geo, 0.34 if offline else 0.30),
        (constraint, 0.28 if offline else 0.25),
        (metrics.preference_hit_rate, 0.22 if offline else 0.20),
        (budget, 0.16 if offline else 0.15),
    ]
    if not offline:
        parts.append((0.0 if metrics.degraded else 1.0, 0.10))

    available = [(value, weight) for value, weight in parts if value is not None]
    total_weight = sum(weight for _, weight in available)
    if total_weight == 0:  # pragma: no cover - every component is None
        return 0.0
    return round(sum(value * weight for value, weight in available) / total_weight * 100, 1)


def measure(case_id: str, plan: TripPlan, request: TripPlanRequest, offline: bool = False) -> CaseMetrics:
    distances = intra_day_distances(plan)
    estimated, unknown = price_counts(plan)
    preference = preference_hit_rate(plan, request)
    metrics = CaseMetrics(
        case_id=case_id,
        days=len(plan.days),
        degraded=plan.degraded,
        avg_intra_day_km=round(sum(distances) / len(distances) / 1000, 2) if distances else 0.0,
        max_intra_day_km=round(max(distances) / 1000, 2) if distances else 0.0,
        duplicate_attractions=duplicate_attractions(plan),
        day_structure_ok=day_structure_ok(plan, request),
        price_estimated=estimated,
        price_unknown=unknown,
        preference_hit_rate=None if preference is None else round(preference, 2),
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
