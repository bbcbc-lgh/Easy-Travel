"""Runs the eval cases through the real planning pipeline and collects metrics."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from evals.judge import judge_plan
from evals.metrics import CaseMetrics, measure
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

    def to_request(self) -> TripPlanRequest:
        return TripPlanRequest(
            city=self.city,
            start_date=date.fromisoformat(self.start_date),
            days=self.days,
            preferences=self.preferences,
            budget=self.budget,
            transportation=self.transportation,
            accommodation=self.accommodation,
        )


@dataclass(slots=True)
class EvalResult:
    case: EvalCase
    metrics: CaseMetrics
    judge: dict | None = None
    error: str | None = None


def load_cases(path: Path | None = None, limit: int | None = None) -> list[EvalCase]:
    raw = json.loads((path or CASES_PATH).read_text(encoding="utf-8"))
    cases = [EvalCase(**item) for item in raw]
    return cases[:limit] if limit else cases


def build_pipeline(mode: str) -> TripPlanningPipeline:
    """``sample`` runs fully offline; ``live`` uses the configured providers."""
    return TripPlanningPipeline(Settings(use_sample_data=(mode == "sample")))


async def run_case(
    case: EvalCase,
    pipeline: TripPlanningPipeline,
    use_judge: bool = False,
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
    verdict = None
    if use_judge and not plan.degraded:
        verdict = await judge_plan(pipeline.graph.planner_agent.llm_planner.gateway, plan)
    return EvalResult(case=case, metrics=metrics, judge=verdict)


async def run_all(
    cases: list[EvalCase],
    pipeline: TripPlanningPipeline,
    use_judge: bool = False,
    offline: bool = False,
    on_progress=None,
) -> list[EvalResult]:
    results: list[EvalResult] = []
    for index, case in enumerate(cases):
        result = await run_case(case, pipeline, use_judge, offline=offline)
        results.append(result)
        if on_progress is not None:
            on_progress(result, index, len(cases))
    return results
