"""Turn the structured JSON logs into the numbers that decide what to fix next.

    cd backend
    LOG_FORMAT=json python -m uvicorn src.api.main:app ... > run.log
    python -m src.cli.quality_report --log run.log

    cat run.log | python -m src.cli.quality_report

Why this exists: "the planner got better" is not a measurement. Every claim this
project makes about its own quality needs a denominator, and until now the two
numbers that matter most - how often the first plan passes the critic, and how
often generation degrades to the rule engine - had a numerator in the logs but no
aggregation anywhere.

The event names read here are the ones the pipeline already emits:

* ``planner.completed``          one successful model-built plan
* ``planner.degraded``           model path failed, rule planner took over
* ``planner.revision_requested`` the critic sent the plan back for one more pass
* ``llm.completed``              token and latency accounting
* ``llm.attempt_failed``         transport / provider failures by reason

Nothing here calls a model, touches the database, or needs the network.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in {None, ""}:  # allow `python src/cli/quality_report.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

#: Events that mean "the model produced this plan".
_COMPLETED = "planner.completed"
_DEGRADED = "planner.degraded"
_REVISION = "planner.revision_requested"
_LLM_DONE = "llm.completed"
_LLM_FAILED = "llm.attempt_failed"
_TRIP_DONE = "planner.finished"


@dataclass(slots=True)
class QualityReport:
    """Everything the log can answer about planner quality.

    Ratios are ``None`` rather than ``0.0`` when their denominator is missing: a
    run with no generations did not score 0% first-pass, it measured nothing, and
    reporting the two the same way is how a dashboard starts lying.
    """

    generations: int = 0
    """Successful plan builds. One trip can produce more than one (a retry does)."""

    degraded: int = 0
    revisions: int = 0
    llm_calls: int = 0
    #: Per *call* latency. Says how fast the provider answers, nothing more.
    llm_elapsed_ms: list[float] = field(default_factory=list)
    #: Per *trip* latency: the number a user actually waits. Kept separate on
    #: purpose - a two-phase pipeline makes calls shorter while the trip stays the
    #: same length, so reporting only the first number reads as a speed-up.
    trip_elapsed_ms: list[float] = field(default_factory=list)
    prompt_tokens: list[int] = field(default_factory=list)
    completion_tokens: list[int] = field(default_factory=list)
    failure_reasons: Counter[str] = field(default_factory=Counter)
    degraded_reasons: Counter[str] = field(default_factory=Counter)

    @property
    def attempts(self) -> int:
        """Planning attempts: every attempt either completed or degraded."""
        return self.generations + self.degraded

    @property
    def trips(self) -> int:
        """How many itineraries were asked for.

        Each retry adds one planning attempt without adding a trip, so the
        denominator of "first pass" has to subtract them - otherwise a single
        retry looks like an extra successful trip and inflates the rate.
        """
        return max(self.attempts - self.revisions, 0)

    @property
    def first_pass_rate(self) -> float | None:
        """Share of requested trips the critic accepted without a retry."""
        if not self.trips:
            return None
        return 1 - min(self.revisions, self.attempts) / self.trips

    @property
    def degraded_rate(self) -> float | None:
        return self.degraded / self.attempts if self.attempts else None

    @property
    def mean_prompt_tokens(self) -> float | None:
        return _mean(self.prompt_tokens)

    @property
    def mean_completion_tokens(self) -> float | None:
        return _mean(self.completion_tokens)

    @property
    def p50_elapsed_ms(self) -> float | None:
        """Median per-call latency."""
        return _percentile(self.llm_elapsed_ms, 50)

    @property
    def p95_elapsed_ms(self) -> float | None:
        """95th percentile per-call latency."""
        return _percentile(self.llm_elapsed_ms, 95)

    @property
    def trip_p50_ms(self) -> float | None:
        return _percentile(self.trip_elapsed_ms, 50)

    @property
    def trip_p95_ms(self) -> float | None:
        return _percentile(self.trip_elapsed_ms, 95)


def _mean(values: list[float] | list[int]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile. Small samples do not justify interpolation."""
    if not values:
        return None
    ordered = sorted(values)
    index = round((pct / 100) * (len(ordered) - 1))
    index = max(0, min(len(ordered) - 1, index))
    return round(ordered[index], 1)


def _number(value: object) -> float | None:
    """Read a numeric log field, ignoring strings, None and booleans."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def summarise(records: Iterable[dict]) -> QualityReport:
    """Aggregate decoded log records. Malformed records are skipped, not fatal."""
    report = QualityReport()
    for record in records:
        if not isinstance(record, dict):
            continue
        event = record.get("event")
        if event == _COMPLETED:
            report.generations += 1
        elif event == _DEGRADED:
            report.degraded += 1
            reason = record.get("reason")
            report.degraded_reasons[str(reason or "unknown")] += 1
        elif event == _REVISION:
            report.revisions += 1
        elif event == _LLM_DONE:
            report.llm_calls += 1
            elapsed = _number(record.get("elapsed_ms"))
            if elapsed is not None:
                report.llm_elapsed_ms.append(elapsed)
            prompt = _number(record.get("prompt_tokens"))
            if prompt is not None:
                report.prompt_tokens.append(int(prompt))
            completion = _number(record.get("completion_tokens"))
            if completion is not None:
                report.completion_tokens.append(int(completion))
        elif event == _LLM_FAILED:
            report.failure_reasons[str(record.get("reason") or "unknown")] += 1
        elif event == _TRIP_DONE:
            elapsed = _number(record.get("elapsed_ms"))
            if elapsed is not None:
                report.trip_elapsed_ms.append(elapsed)
    return report


def iter_records(lines: Iterable[str]) -> Iterator[dict]:
    """Decode JSON lines, skipping anything that is not a JSON object."""
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}ms"


def _tokens(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def format_report(report: QualityReport) -> str:
    lines = [
        f"行程数     : {report.trips}",
        f"规划尝试   : {report.attempts}（成功 {report.generations} · 降级 {report.degraded}）",
        f"重排请求   : {report.revisions}",
        f"首轮通过率 : {_percent(report.first_pass_rate)}",
        f"降级率     : {_percent(report.degraded_rate)}",
        f"模型调用   : {report.llm_calls} 次",
        f"单次调用   : P50 {_ms(report.p50_elapsed_ms)} · P95 {_ms(report.p95_elapsed_ms)}",
        f"整单生成   : P50 {_ms(report.trip_p50_ms)} · P95 {_ms(report.trip_p95_ms)}（用户实际等待）",
        f"token 均值 : 输入 {_tokens(report.mean_prompt_tokens)} · 输出 {_tokens(report.mean_completion_tokens)}",
    ]
    if report.degraded_reasons:
        reasons = "、".join(f"{key}×{count}" for key, count in report.degraded_reasons.most_common())
        lines.append(f"降级原因   : {reasons}")
    if report.failure_reasons:
        reasons = "、".join(f"{key}×{count}" for key, count in report.failure_reasons.most_common())
        lines.append(f"调用失败   : {reasons}")
    if report.attempts == 0:
        lines.append("")
        lines.append("这次日志里没有一次规划尝试：首轮通过率无从计算（不是 0%）。")
    return "\n".join(lines)


def _read_log_lines(path: Path) -> list[str]:
    """Read a log file whatever encoding the shell that produced it used.

    ``python -m evals > run.log`` writes UTF-8, but a PowerShell redirect
    (``*> run.log``) writes UTF-16LE with a BOM. Both are legitimate ways to
    capture this output on Windows, so sniff the BOM instead of trusting UTF-8.
    """
    raw = path.read_bytes()
    for bom, encoding in (
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
        (b"\xef\xbb\xbf", "utf-8-sig"),
    ):
        if raw.startswith(bom):
            return raw.decode(encoding, errors="replace").lstrip("\ufeff").splitlines()
    return raw.decode("utf-8", errors="replace").lstrip("\ufeff").splitlines()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise planner quality from JSON logs")
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="JSON log file (LOG_FORMAT=json); omit to read stdin",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.log is not None:
        if not args.log.is_file():
            print(f"日志文件不存在：{args.log}", file=sys.stderr)
            return 1
        lines = _read_log_lines(args.log)
    else:
        lines = sys.stdin.read().splitlines()

    report = summarise(iter_records(lines))
    if args.json:
        payload = {
            "trips": report.trips,
            "attempts": report.attempts,
            "generations": report.generations,
            "degraded": report.degraded,
            "revisions": report.revisions,
            "llm_calls": report.llm_calls,
            "first_pass_rate": report.first_pass_rate,
            "degraded_rate": report.degraded_rate,
            "p50_elapsed_ms": report.p50_elapsed_ms,
            "p95_elapsed_ms": report.p95_elapsed_ms,
            "trip_p50_ms": report.trip_p50_ms,
            "trip_p95_ms": report.trip_p95_ms,
            "mean_prompt_tokens": report.mean_prompt_tokens,
            "mean_completion_tokens": report.mean_completion_tokens,
            "failure_reasons": dict(report.failure_reasons),
            "degraded_reasons": dict(report.degraded_reasons),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
