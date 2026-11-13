import json

from src.cli.quality_report import (
    QualityReport,
    format_report,
    iter_records,
    main,
    summarise,
)


def _record(event: str, **fields) -> dict:
    return {"event": event, **fields}


def test_summarise_counts_each_event_type():
    records = [
        _record("planner.completed", source="llm"),
        _record("planner.completed", source="llm"),
        _record("planner.degraded", reason="llm_provider_timeout"),
        _record("planner.revision_requested", revision=1),
        _record("llm.completed", elapsed_ms=1000, prompt_tokens=800, completion_tokens=5000),
        _record("llm.completed", elapsed_ms=3000, prompt_tokens=1000, completion_tokens=7000),
        _record("llm.attempt_failed", reason="rate_limited"),
        _record("http.request", path="/api/health"),
    ]

    report = summarise(records)

    assert report.generations == 2
    assert report.degraded == 1
    assert report.revisions == 1
    assert report.llm_calls == 2
    assert report.failure_reasons["rate_limited"] == 1
    assert report.degraded_reasons["llm_provider_timeout"] == 1


def test_first_pass_rate_is_one_when_nothing_was_retried():
    report = summarise([_record("planner.completed"), _record("planner.completed")])
    assert report.first_pass_rate == 1.0


def test_first_pass_rate_drops_when_the_critic_asked_for_a_retry():
    """4 trips, one of which needed a retry: 5 planning attempts, 4 trips."""
    report = summarise(
        [
            _record("planner.completed"),
            _record("planner.completed"),
            _record("planner.completed"),
            _record("planner.completed"),
            _record("planner.completed"),
            _record("planner.revision_requested"),
        ]
    )
    assert report.attempts == 5
    assert report.trips == 4
    assert report.first_pass_rate == 0.75


def test_a_retry_is_not_counted_as_an_extra_trip():
    """`planner.completed` fires once per attempt; the denominator must be trips.

    Counting completions alone reported 80% here, when the honest answer is 75%:
    the retry inflated both sides of the ratio.
    """
    report = summarise([_record("planner.completed")] * 5 + [_record("planner.revision_requested")])

    assert report.generations == 5
    assert report.trips == 4
    assert report.first_pass_rate == 0.75


def test_an_inconsistent_log_reports_no_rate_instead_of_a_negative_one():
    """A log spanning a config change can hold more retries than attempts."""
    report = summarise(
        [
            _record("planner.completed"),
            _record("planner.revision_requested"),
            _record("planner.revision_requested"),
        ]
    )
    assert report.revisions == 2
    assert report.trips == 0
    assert report.first_pass_rate is None


def test_ratios_are_none_not_zero_when_nothing_was_measured():
    """0% and "no data" are different answers; reporting them the same is a lie."""
    report = summarise([])

    assert report.generations == 0
    assert report.first_pass_rate is None
    assert report.degraded_rate is None
    assert report.p50_elapsed_ms is None
    assert report.mean_prompt_tokens is None
    assert "不是 0%" in format_report(report)


def test_degraded_rate_counts_attempts_not_only_successes():
    report = summarise([_record("planner.completed"), _record("planner.degraded")])
    assert report.degraded_rate == 0.5


def test_percentile_uses_nearest_rank_and_survives_a_single_sample():
    report = summarise(
        [
            _record("llm.completed", elapsed_ms=100),
            _record("llm.completed", elapsed_ms=200),
            _record("llm.completed", elapsed_ms=300),
        ]
    )
    assert report.p50_elapsed_ms == 200
    assert report.p95_elapsed_ms == 300

    single = summarise([_record("llm.completed", elapsed_ms=42)])
    assert single.p50_elapsed_ms == 42
    assert single.p95_elapsed_ms == 42


def test_numeric_fields_are_ignored_when_they_arrive_as_strings():
    """Log fields go through a formatter that may stringify; never crash on them."""
    report = summarise([_record("llm.completed", elapsed_ms="1200", prompt_tokens=None)])

    assert report.llm_elapsed_ms == []
    assert report.prompt_tokens == []
    assert report.llm_calls == 1


def test_iter_records_skips_malformed_lines_and_non_objects():
    lines = [
        '{"event": "planner.completed"}',
        "",
        "   ",
        "not json at all",
        '{"event": "planner.degraded", "reason": "x"}',
        "[1, 2, 3]",
        '{"truncated": ',
    ]

    records = list(iter_records(lines))

    assert [record["event"] for record in records] == ["planner.completed", "planner.degraded"]


def test_format_report_prints_the_numbers_this_tool_exists_for():
    report = summarise(
        [
            _record("planner.completed"),
            _record("planner.completed"),
            _record("planner.completed"),
            _record("planner.revision_requested"),
            _record("llm.completed", elapsed_ms=28000, prompt_tokens=900, completion_tokens=4000),
        ]
    )
    text = format_report(report)

    assert "行程数     : 2" in text
    assert "首轮通过率 : 50%" in text
    assert "单次调用   : P50 28000ms" in text
    assert "输入 900" in text


def test_trip_latency_is_kept_apart_from_call_latency() -> None:
    """A two-phase pipeline shortens calls while the trip stays the same length.

    Reporting only per-call latency made the pipeline look several times faster
    than the user experiences; the two numbers have to stay separate.
    """
    report = summarise(
        [
            _record("planner.finished", elapsed_ms=32000),
            _record("planner.finished", elapsed_ms=40000),
            _record("llm.completed", elapsed_ms=6000),
            _record("llm.completed", elapsed_ms=7000),
        ]
    )

    assert report.trip_p50_ms == 32000
    assert report.p50_elapsed_ms == 6000
    text = format_report(report)
    assert "整单生成   : P50 32000ms" in text
    assert "单次调用   : P50 6000ms" in text


def test_a_log_without_trip_events_reports_no_trip_latency() -> None:
    """Old logs predate `planner.finished`; they must not fake a trip number."""
    report = summarise([_record("llm.completed", elapsed_ms=6000)])

    assert report.trip_p50_ms is None
    assert "整单生成   : P50 n/a" in format_report(report)


def test_main_reads_a_log_file(tmp_path, capsys):
    log = tmp_path / "run.log"
    log.write_text(
        "\n".join(
            [
                json.dumps({"event": "planner.completed"}),
                json.dumps({"event": "planner.completed"}),
                json.dumps({"event": "planner.completed"}),
                json.dumps({"event": "planner.revision_requested"}),
            ]
        ),
        encoding="utf-8",
    )

    assert main(["--log", str(log)]) == 0
    assert "首轮通过率 : 50%" in capsys.readouterr().out


def test_main_supports_json_output_for_scripting(tmp_path, capsys):
    log = tmp_path / "run.log"
    log.write_text(json.dumps({"event": "planner.completed"}), encoding="utf-8")

    assert main(["--log", str(log), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["generations"] == 1
    assert payload["first_pass_rate"] == 1.0


def test_main_fails_clearly_when_the_log_is_missing(tmp_path, capsys):
    assert main(["--log", str(tmp_path / "nope.log")]) == 1
    assert "不存在" in capsys.readouterr().err


def test_main_reads_a_utf16_log_written_by_a_powershell_redirect(tmp_path, capsys):
    """`*> run.log` in PowerShell writes UTF-16LE with a BOM, not UTF-8."""
    log = tmp_path / "run.log"
    body = "\n".join(
        [
            json.dumps({"event": "planner.completed"}),
            json.dumps({"event": "planner.completed"}),
            json.dumps({"event": "planner.completed"}),
            json.dumps({"event": "planner.revision_requested"}),
        ]
    )
    log.write_bytes(b"\xff\xfe" + body.encode("utf-16-le"))

    assert main(["--log", str(log)]) == 0
    assert "首轮通过率 : 50%" in capsys.readouterr().out


def test_main_reads_a_utf8_bom_log(tmp_path, capsys):
    log = tmp_path / "run.log"
    log.write_bytes(b"\xef\xbb\xbf" + json.dumps({"event": "planner.completed"}).encode("utf-8"))

    assert main(["--log", str(log)]) == 0
    assert "首轮通过率 : 100%" in capsys.readouterr().out


def test_report_dataclass_defaults_are_empty_not_shared():
    first = QualityReport()
    second = QualityReport()
    first.failure_reasons["x"] += 1

    assert second.failure_reasons == {}
    assert first.llm_elapsed_ms == []
