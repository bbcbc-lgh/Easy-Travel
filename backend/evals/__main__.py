"""Command line entry point.

python -m evals --mode sample --limit 5
python -m evals --mode live --limit 5 --min-usable-ratio 0.8
"""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from evals.gates import summarise, violations
from evals.report import render_report
from evals.runner import EvalResult, build_pipeline, load_cases, run_all
from evals.usability import RULES
from src.config import settings
from src.service.logging import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EasyTravel itinerary evals")
    parser.add_argument("--mode", choices=["sample", "live"], default="sample")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N cases")
    parser.add_argument(
        "--ids",
        default=None,
        help="comma-separated case ids to run (e.g. long-xa-14,long-bj-7)",
    )
    parser.add_argument("--out", type=Path, default=None, help="report path")
    # Thresholds. Omitted means "just report"; CI passes them explicitly.
    parser.add_argument("--min-score", type=float, default=None, help="fail when the mean score is below this")
    parser.add_argument("--max-errors", type=int, default=None, help="fail when more cases than this raised")
    parser.add_argument(
        "--max-degraded-ratio",
        type=float,
        default=None,
        help="fail when more than this share of cases fell back to the rule planner",
    )
    parser.add_argument(
        "--min-usable-ratio",
        type=float,
        default=None,
        help="fail when fewer than this share of plans could be followed as written",
    )
    # An eval run is also a measurement of the planner: with INFO logging and
    # LOG_FORMAT=json, its stdout can be fed straight into src.cli.quality_report.
    # The default stays ERROR so a normal run prints only the report.
    parser.add_argument(
        "--log-level",
        default="ERROR",
        help="log level for the pipeline (INFO makes completion/retry events visible)",
    )
    return parser.parse_args(argv)


async def _main(args: argparse.Namespace) -> int:
    configure_logging(level=args.log_level, fmt=settings.log_format)
    cases = load_cases(
        limit=args.limit,
        ids=[item.strip() for item in args.ids.split(",") if item.strip()] if args.ids else None,
    )
    if not cases:
        print("no eval cases found")
        return 1

    pipeline = build_pipeline(args.mode)
    offline = args.mode == "sample"
    results: list[EvalResult] = []

    def on_progress(result: EvalResult, index: int, total: int) -> None:
        error = f" error={result.error}" if result.error else ""
        print(
            f"[{index + 1}/{total}] {result.case.id:<14} "
            f"score={result.metrics.score:5.1f} geo={result.metrics.avg_intra_day_km:5.1f}km "
            f"degraded={result.metrics.degraded}{error}"
        )

    results = await run_all(
        cases,
        pipeline,
        offline=offline,
        on_progress=on_progress,
    )

    output = args.out or REPO_ROOT / "outputs" / f"eval-{args.mode}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = render_report(
        results,
        mode=args.mode,
        generated_at=datetime.now(UTC),
        offline=offline,
    )
    output.write_text(report, encoding="utf-8")

    summary = summarise(results)
    print()
    print(f"cases      : {summary.cases}")
    print(f"mean score : {summary.mean_score if summary.mean_score is not None else 'n/a'}")
    print(f"degraded   : {summary.degraded}/{summary.cases}")
    print(f"errors     : {summary.errors}")
    if summary.usability is not None:
        print(
            f"usable     : {summary.usability.usable}/{summary.usability.cases} "
            f"({summary.usable_ratio:.0%} 可直接照着走)"
        )
        for rule in RULES:
            count = summary.usability.failures_by_rule.get(rule.key, 0)
            if count:
                print(f"  - {rule.label}：{count} 处")
    print(f"report     : {output}")

    problems = violations(
        summary,
        min_score=args.min_score,
        max_errors=args.max_errors,
        max_degraded_ratio=args.max_degraded_ratio,
        min_usable_ratio=args.min_usable_ratio,
    )
    if problems:
        print()
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    gated = (
        args.min_score,
        args.max_errors,
        args.max_degraded_ratio,
        args.min_usable_ratio,
    )
    if any(value is not None for value in gated):
        print("thresholds : passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
