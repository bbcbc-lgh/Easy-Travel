"""Turn an eval run into a pass/fail signal.

The runner has always produced a number; nothing acted on it, so the CI step could
only fail if the harness itself crashed. These thresholds are what make a quality
regression (a prompt change, a scheduler edit, a cheaper model) show up as a red
build instead of a line nobody reads.

Every threshold is optional: a plain `python -m evals` still just reports, and CI
opts in explicitly.
"""

from dataclasses import dataclass
from statistics import mean

from evals.runner import EvalResult


@dataclass(slots=True)
class Summary:
    cases: int
    scored: int
    mean_score: float | None
    degraded: int
    errors: int

    @property
    def degraded_ratio(self) -> float:
        return self.degraded / self.cases if self.cases else 0.0

    @property
    def error_ratio(self) -> float:
        return self.errors / self.cases if self.cases else 0.0


def summarise(results: list[EvalResult]) -> Summary:
    scored = [result.metrics.score for result in results if result.error is None]
    return Summary(
        cases=len(results),
        scored=len(scored),
        mean_score=round(mean(scored), 1) if scored else None,
        degraded=sum(1 for result in results if result.metrics.degraded),
        errors=sum(1 for result in results if result.error is not None),
    )


def violations(
    summary: Summary,
    *,
    min_score: float | None = None,
    max_errors: int | None = None,
    max_degraded_ratio: float | None = None,
) -> list[str]:
    """Human-readable reasons the run should fail. Empty means it passed."""
    problems: list[str] = []

    if min_score is not None:
        if summary.mean_score is None:
            problems.append(f"no case produced a score (expected mean >= {min_score})")
        elif summary.mean_score < min_score:
            problems.append(f"mean score {summary.mean_score} is below the {min_score} floor")

    if max_errors is not None and summary.errors > max_errors:
        problems.append(f"{summary.errors} case(s) raised, allowed {max_errors}")

    if max_degraded_ratio is not None and summary.degraded_ratio > max_degraded_ratio:
        problems.append(
            f"{summary.degraded_ratio:.0%} of cases fell back to the rule planner, allowed {max_degraded_ratio:.0%}"
        )

    return problems
