"""Runs the eval cases through the real planning pipeline and collects metrics."""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from evals.metrics import CaseMetrics, measure
from evals.usability import CaseUsability, assess
from src.api.deps import TripPlanningPipeline
from src.config import Settings
from src.model.schemas import TripPlanRequest

CASES_PATH = Path(__file__).with_name("cases.json")


@dataclass(slots=True)
class EvalCase:
    id: str
    city: str
    start_date: str
    days: int
    preferences: str
    # Mirrors TripPlanRequest's Literal so to_request() is type-checkable; values
    # still come from cases.json, where pydantic enforces them at request time.
    budget: Literal["经济", "中等", "舒适", "豪华"]
    transportation: str
    accommodation: str
    #: Optional so older case files keep working.
    must_visit: list[str] = field(default_factory=list)
    arrival_time: str | None = None
    departure_time: str | None = None

    def to_request(self) -> TripPlanRequest:
        return TripPlanRequest(
            city=self.city,
            start_date=date.fromisoformat(self.start_date),
            days=self.days,
            preferences=self.preferences,
            budget=self.budget,
            transportation=self.transportation,
            accommodation=self.accommodation,
            must_visit=list(self.must_visit),
            arrival_time=self.arrival_time,
            departure_time=self.departure_time,
        )


@dataclass(slots=True)
class EvalResult:
    case: EvalCase
    metrics: CaseMetrics
    #: Whether a traveller could follow the plan as written; None when the case
    #: never produced one.
    usability: CaseUsability | None = None
    error: str | None = None


def load_cases(
    path: Path | None = None,
    limit: int | None = None,
    ids: list[str] | None = None,
) -> list[EvalCase]:
    raw = json.loads((path or CASES_PATH).read_text(encoding="utf-8"))
    cases = [EvalCase(**item) for item in raw]
    if ids:
        wanted = set(ids)
        cases = [case for case in cases if case.id in wanted]
    return cases[:limit] if limit else cases


def build_pipeline(mode: str) -> TripPlanningPipeline:
    """``sample`` runs fully offline; ``live`` uses the configured providers."""
    return TripPlanningPipeline(Settings(use_sample_data=(mode == "sample")))


async def run_case(
    case: EvalCase,
    pipeline: TripPlanningPipeline,
    offline: bool = False,
) -> EvalResult:
    request = case.to_request()
    try:
        plan = await pipeline.run(request)
    except Exception as exc:  # noqa: BLE001 - a failed case is data, not a crash
        return EvalResult(
            case=case,
            # A blank record: every field defaults to "nothing measured", so this
            # cannot break when CaseMetrics grows a field.
            metrics=CaseMetrics(case_id=case.id, degraded=True),
            error=f"{type(exc).__name__}: {exc}",
        )

    metrics = measure(case.id, plan, request, offline=offline)
    usability = assess(plan, request, case.id)
    return EvalResult(case=case, metrics=metrics, usability=usability)


async def run_all(
    cases: list[EvalCase],
    pipeline: TripPlanningPipeline,
    offline: bool = False,
    on_progress=None,
) -> list[EvalResult]:
    results: list[EvalResult] = []
    for index, case in enumerate(cases):
        result = await run_case(case, pipeline, offline=offline)
        results.append(result)
        if on_progress is not None:
            on_progress(result, index, len(cases))
    return results
