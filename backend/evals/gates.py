"""Turn an eval run into a pass/fail signal.

The runner has always produced a number; nothing acted on it, so the CI step could
only fail if the harness itself crashed. These thresholds are what make a quality
regression (a prompt change, a scheduler edit, a cheaper model) show up as a red
build instead of a line nobody reads.

Two different questions are gated here, and the second one is the point for a tool
that saves the user research:
  * ``mean_score`` - how good the itineraries are overall;
  * ``usable_ratio`` - how many of them a traveller could follow as written.

Every threshold is optional: a plain `python -m evals` still just reports, and CI
opts in explicitly.
"""

from dataclasses import dataclass, field
from statistics import mean

from evals.runner import EvalResult
from evals.usability import UsabilitySummary
from evals.usability import summarise as summarise_usability


@dataclass(slots=True)
class Summary:
    cases: int
    scored: int
    mean_score: float | None
    degraded: int
    errors: int
    usability: UsabilitySummary | None = None
    unusable_examples: list[str] = field(default_factory=list)

    @property
    def degraded_ratio(self) -> float:
        return self.degraded / self.cases if self.cases else 0.0

    @property
    def error_ratio(self) -> float:
        return self.errors / self.cases if self.cases else 0.0

    @property
    def usable_ratio(self) -> float:
        """A case that never produced a plan counts as unusable, not as missing.

        The denominator is every case, not just the ones that produced a verdict:
        a crash must drag the ratio down, otherwise losing cases would look like
        improving usability.
        """
        if self.usability is None or not self.cases:
            return 0.0
        return self.usability.usable / self.cases


def summarise(results: list[EvalResult]) -> Summary:
    scored = [result.metrics.score for result in results if result.error is None]
    usability_results = [result.usability for result in results if result.usability is not None]
    return Summary(
        cases=len(results),
        scored=len(scored),
        mean_score=round(mean(scored), 1) if scored else None,
        degraded=sum(1 for result in results if result.metrics.degraded),
        errors=sum(1 for result in results if result.error is not None),
        usability=summarise_usability(usability_results) if usability_results else None,
        unusable_examples=[result.case.id for result in results if result.usability and not result.usability.usable],
    )


def violations(
    summary: Summary,
    *,
    min_score: float | None = None,
    max_errors: int | None = None,
    max_degraded_ratio: float | None = None,
    min_usable_ratio: float | None = None,
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

    if min_usable_ratio is not None:
        if summary.usability is None:
            problems.append(f"no case produced a usable-plan verdict (expected >= {min_usable_ratio:.0%})")
        elif summary.usable_ratio < min_usable_ratio:
            examples = ", ".join(summary.unusable_examples[:5]) or "none"
            problems.append(
                f"{summary.usable_ratio:.0%} of plans are directly usable, "
                f"below the {min_usable_ratio:.0%} floor (e.g. {examples})"
            )

    return problems
