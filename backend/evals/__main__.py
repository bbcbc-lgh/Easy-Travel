"""Command line entry point.

    python -m evals --mode sample --limit 5
    python -m evals --mode live --judge --limit 3
"""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from evals.report import render_report
from evals.runner import EvalResult, build_pipeline, load_cases, run_all
from src.service.logging import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EasyTravel itinerary evals")
    parser.add_argument("--mode", choices=["sample", "live"], default="sample")
    parser.add_argument("--limit", type=int, default=None, help="only run the first N cases")
    parser.add_argument("--judge", action="store_true", help="also run the LLM-as-judge pass (live mode)")
    parser.add_argument("--out", type=Path, default=None, help="report path")
    return parser.parse_args(argv)


async def _main(args: argparse.Namespace) -> int:
    configure_logging(level="ERROR")
    cases = load_cases(limit=args.limit)
    if not cases:
        print("no eval cases found")
        return 1

    pipeline = build_pipeline(args.mode)
    offline = args.mode == "sample"
    results: list[EvalResult] = []

    def on_progress(result: EvalResult, index: int, total: int) -> None:
        judge = f" judge={result.judge['score']}" if result.judge else ""
        error = f" error={result.error}" if result.error else ""
        print(
            f"[{index + 1}/{total}] {result.case.id:<14} "
            f"score={result.metrics.score:5.1f} geo={result.metrics.avg_intra_day_km:5.1f}km "
            f"degraded={result.metrics.degraded}{judge}{error}"
        )

    results = await run_all(
        cases,
        pipeline,
        use_judge=args.judge,
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

    scored = [result.metrics.score for result in results if result.error is None]
    print()
    print(f"cases      : {len(results)}")
    print(f"mean score : {mean(scored):.1f}" if scored else "mean score : n/a")
    print(f"degraded   : {sum(1 for r in results if r.metrics.degraded)}/{len(results)}")
    print(f"report     : {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
