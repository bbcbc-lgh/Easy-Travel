import asyncio
from datetime import date

import pytest

from evals.gates import summarise, violations
from evals.judge import build_plan_summary
from evals.metrics import (
    CaseMetrics,
    budget_deviation,
    cap_violations,
    composite_score,
    day_structure_ok,
    duplicate_attractions,
    intra_day_distances,
    measure,
    preference_hit_rate,
    price_counts,
    reference_budget,
)
from evals.runner import EvalResult, build_pipeline, load_cases, run_case
from evals.usability import CaseUsability, Failure
from src.model.schemas import Attraction, DayPlan, Hotel, Location, Meal, TripPlan, TripPlanRequest


def request(**overrides) -> TripPlanRequest:
    payload = {
        "city": "杭州",
        "start_date": date(2026, 11, 20),
        "days": 2,
        "preferences": "历史文化",
        "budget": "中等",
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
    }
    payload.update(overrides)
    return TripPlanRequest(**payload)


def attraction(name: str, longitude: float, latitude: float, category: str = "风景名胜") -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=Location(longitude=longitude, latitude=latitude),
        category=category,
        ticket_price=30,
        price_source="api",
        source="amap",
        description=f"{name} 简介",
    )


def meal(name: str, cost: int, meal_type: str) -> Meal:
    return Meal(
        type=meal_type,
        name=name,
        address="杭州市",
        location=Location(longitude=120.15, latitude=30.27),
        estimated_cost=cost,
        price_source="api",
        source="amap",
    )


def build_plan(days: int = 2, day_attractions: int = 2, degraded: bool = True) -> TripPlan:
    hotel = Hotel(name="测试酒店", address="杭州市", estimated_cost=300, source="amap")
    plan_days = []
    for index in range(days):
        plan_days.append(
            DayPlan(
                date=f"2026-11-{20 + index:02d}",
                day_index=index,
                description="测试行程",
                transportation="公共交通",
                accommodation="经济型酒店",
                hotel=hotel,
                attractions=[
                    attraction(f"杭州博物馆{index}-{i}", 120.150 + i * 0.01, 30.270) for i in range(day_attractions)
                ],
                meals=[
                    meal("早餐铺", 20, "breakfast"),
                    meal("面馆", 40, "lunch"),
                    meal("家常菜", 60, "dinner"),
                ],
            )
        )
    return TripPlan(
        city="杭州",
        start_date="2026-11-20",
        end_date=f"2026-11-{19 + days:02d}",
        days=plan_days,
        overall_suggestions="测试",
        degraded=degraded,
        degraded_reason="llm_disabled" if degraded else None,
    )


def test_eval_cases_are_valid_and_numerous() -> None:
    cases = load_cases()

    assert len(cases) >= 20
    assert len({case.id for case in cases}) == len(cases)
    for case in cases:
        assert 1 <= case.days <= 14
        assert case.budget in {"经济", "中等", "舒适", "豪华"}
        assert case.city


def test_intra_day_distance_excludes_the_hotel_leg() -> None:
    plan = build_plan(days=1, day_attractions=3)

    distances = intra_day_distances(plan)

    assert len(distances) == 1
    # Two hops of 0.01 longitude at this latitude: ~2 km in total, not hotel-relative.
    assert 1_500 < distances[0] < 2_500


def test_duplicate_attractions_are_counted() -> None:
    plan = build_plan(days=2)
    plan.days[1].attractions[0] = plan.days[0].attractions[0]

    assert duplicate_attractions(plan) == 1


def test_day_structure_requires_one_to_three_attractions() -> None:
    good = build_plan(days=2)
    empty = build_plan(days=2)
    empty.days[0].attractions = []

    assert day_structure_ok(good, request(days=2)) is True
    assert day_structure_ok(empty, request(days=2)) is False
    assert day_structure_ok(good, request(days=3)) is False


def test_cap_violations_follow_the_budget_tier() -> None:
    plan = build_plan(days=1)
    plan.days[0].meals[0].estimated_cost = 120

    assert cap_violations(plan, request(days=1, budget="中等")) == 1
    assert cap_violations(plan, request(days=1, budget="豪华")) == 0


def test_price_counts_distinguish_sources() -> None:
    plan = build_plan(days=1)
    plan.days[0].attractions[0].price_source = "unknown"

    estimated, unknown = price_counts(plan)

    assert unknown == 1
    assert estimated >= 0


def test_preference_hit_rate_matches_keywords() -> None:
    plan = build_plan(days=1, day_attractions=2)

    assert preference_hit_rate(plan, request(preferences="历史文化")) == 1.0
    assert preference_hit_rate(plan, request(preferences="亲子")) == 0.0


def test_preference_hit_rate_ignores_model_prose() -> None:
    """Regression: appending the preference string to a description used to earn 100%.

    The sample data did exactly that, so a plan of unrelated stops scored a perfect
    preference fit as long as one keyword appeared in the prose. The metric must
    only look at what the place *is*.
    """
    plan = build_plan(days=1, day_attractions=2)
    for day in plan.days:
        for index, item in enumerate(day.attractions):
            item.name = f"杭州地标{index}"
            item.category = "地标"
            item.description = "已结合你的偏好：历史文化，带儿童出行，需要无障碍设施。"

    assert preference_hit_rate(plan, request(preferences="历史文化")) == 0.0


def test_reference_budget_grows_with_tier() -> None:
    economy = reference_budget(request(budget="经济"))
    luxury = reference_budget(request(budget="豪华"))

    assert luxury > economy


def test_budget_deviation_is_relative() -> None:
    plan = build_plan(days=1)
    reference = reference_budget(request(days=1))
    plan.budget = type("B", (), {"total": reference * 2})()

    assert budget_deviation(plan, request(days=1)) == pytest.approx(1.0, abs=0.01)


def test_offline_score_does_not_punish_the_rule_planner() -> None:
    plan = build_plan(days=2, degraded=True)
    online = measure("x", plan, request(days=2), offline=False)
    offline = measure("x", plan, request(days=2), offline=True)

    assert offline.score > online.score


def test_composite_score_is_bounded() -> None:
    plan = build_plan(days=1)
    metrics = measure("x", plan, request(days=1))

    assert 0 <= composite_score(metrics) <= 100


def test_runner_executes_a_case_offline() -> None:
    case = load_cases(limit=1)[0]
    pipeline = build_pipeline("sample")

    result = asyncio.run(run_case(case, pipeline, offline=True))

    assert result.error is None
    assert result.metrics.days == case.days
    assert result.metrics.score > 0


def test_a_failed_case_is_recorded_instead_of_raising() -> None:
    """Regression: the failure path hand-built CaseMetrics and missed a field, so a
    provider error crashed the eval run instead of being reported as one bad case."""

    class ExplodingPipeline:
        async def run(self, request: TripPlanRequest):
            raise RuntimeError("provider down")

    case = load_cases(limit=1)[0]

    result = asyncio.run(run_case(case, ExplodingPipeline(), offline=False))

    assert result.error == "RuntimeError: provider down"
    assert result.metrics.case_id == case.id
    assert result.metrics.days == 0
    assert result.metrics.score == 0.0
    assert result.metrics.degraded is True


def test_judge_summary_lists_every_day() -> None:
    summary = build_plan_summary(build_plan(days=3))

    assert "第 1 天" in summary
    assert "第 3 天" in summary
    assert "预算合计" in summary


# --- gates: turning a score into a pass/fail signal ---------------------------


def _results(*specs: tuple[float, bool, bool]) -> list[EvalResult]:
    """Build results from (score, degraded, errored) triples."""
    case = load_cases(limit=1)[0]
    results = []
    for index, (score, degraded, errored) in enumerate(specs):
        results.append(
            EvalResult(
                case=case,
                metrics=CaseMetrics(case_id=f"c{index}", degraded=degraded, score=score),
                error="boom" if errored else None,
            )
        )
    return results


def test_summary_reports_mean_and_ratios() -> None:
    summary = summarise(_results((90.0, False, False), (70.0, True, False), (0.0, True, True)))

    assert summary.cases == 3
    assert summary.scored == 2
    assert summary.mean_score == 80.0
    assert summary.degraded == 2
    assert summary.errors == 1
    assert summary.degraded_ratio == pytest.approx(2 / 3)


def test_no_thresholds_means_no_violations() -> None:
    """A plain run must stay a report, never a failure."""
    assert violations(summarise(_results((10.0, True, True)))) == []


def test_a_low_mean_score_is_a_violation() -> None:
    summary = summarise(_results((72.3, True, False)))

    assert violations(summary, min_score=70) == []
    problems = violations(summary, min_score=80)

    assert len(problems) == 1
    assert "72.3" in problems[0] and "80" in problems[0]


def test_a_run_with_no_score_fails_a_score_threshold() -> None:
    summary = summarise(_results((0.0, True, True)))

    problems = violations(summary, min_score=70)

    assert problems and "no case produced a score" in problems[0]


def test_error_and_degraded_thresholds() -> None:
    summary = summarise(_results((80.0, True, False), (80.0, False, True)))

    assert violations(summary, max_errors=1) == []
    assert len(violations(summary, max_errors=0)) == 1
    # Exactly half the cases fell back to the rule planner.
    assert summary.degraded_ratio == pytest.approx(0.5)
    assert violations(summary, max_degraded_ratio=0.5) == []
    assert len(violations(summary, max_degraded_ratio=0.4)) == 1


# --- gates: usability ---------------------------------------------------------


def _with_usability(*specs: tuple[bool, str]) -> list[EvalResult]:
    """Build results from (usable, case_id) pairs."""
    case = load_cases(limit=1)[0]
    results = []
    for usable, case_id in specs:
        verdict = CaseUsability(
            case_id=case_id,
            failures=[] if usable else [Failure("meals_complete", "第 1 天缺少早餐")],
        )
        results.append(EvalResult(case=case, metrics=CaseMetrics(case_id=case_id, score=80.0), usability=verdict))
    return results


def test_a_fully_usable_run_meets_a_hundred_percent_floor() -> None:
    summary = summarise(_with_usability((True, "a"), (True, "b")))

    assert summary.usable_ratio == 1.0
    assert violations(summary, min_usable_ratio=1.0) == []


def test_an_unusable_plan_breaks_the_floor_and_names_itself() -> None:
    summary = summarise(_with_usability((True, "a"), (False, "b")))

    assert summary.usable_ratio == 0.5
    problems = violations(summary, min_usable_ratio=1.0)

    assert len(problems) == 1
    assert "50%" in problems[0]
    assert "b" in problems[0]


def test_a_case_that_never_produced_a_plan_counts_as_unusable() -> None:
    case = load_cases(limit=1)[0]
    results = [
        *_with_usability((True, "a"), (True, "b")),
        EvalResult(case=case, metrics=CaseMetrics(case_id="c"), usability=None, error="boom"),
    ]

    summary = summarise(results)

    assert summary.cases == 3
    assert summary.usable_ratio == pytest.approx(2 / 3)


def test_a_run_without_any_verdict_cannot_meet_a_usability_floor() -> None:
    summary = summarise(_results((80.0, False, False)))

    problems = violations(summary, min_usable_ratio=0.9)

    assert problems and "no case produced a usable-plan verdict" in problems[0]
