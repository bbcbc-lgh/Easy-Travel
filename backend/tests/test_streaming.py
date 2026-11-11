import json


def parse_events(body: str) -> list[dict]:
    events = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name = "message"
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if not data_lines:
            continue
        events.append({"event": name, "data": json.loads("\n".join(data_lines))})
    return events


def test_stream_works_without_client_id() -> None:
    """No header is required: header-less callers land in the local bucket."""
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app).stream("POST", "/api/trip/plan/stream", json={}) as response:
        # Empty body must be a validation error, not an auth error.
        assert response.status_code == 422


def test_stream_emits_stages_then_plan(owned_client, plan_payload, offline_mode) -> None:
    with owned_client.stream("POST", "/api/trip/plan/stream", json=plan_payload()) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = parse_events(body)
    stages = [event["data"] for event in events if event["event"] == "stage"]
    plans = [event["data"] for event in events if event["event"] == "plan"]

    stage_names = [stage["stage"] for stage in stages]
    assert stage_names.count("collect_candidates") == 2
    assert stage_names.count("create_plan") == 2
    assert "enrich_routes" in stage_names
    assert "review_plan" in stage_names
    assert any(stage["status"] == "done" for stage in stages)

    assert len(plans) == 1
    plan = plans[0]["plan"]
    assert plan["id"]
    assert plan["city"] == "杭州"
    assert plan["degraded"] is True
    assert plans[0]["elapsed_ms"] > 0

    listed = owned_client.get("/api/trip/plans").json()
    assert [item["id"] for item in listed] == [plan["id"]]


def test_stream_reports_quota_as_error_event(owned_client, plan_payload, offline_mode, monkeypatch) -> None:
    from src.api.deps import get_generation_guard
    from src.config import settings

    monkeypatch.setattr(settings, "plan_daily_limit", 1)
    get_generation_guard.cache_clear()

    with owned_client.stream("POST", "/api/trip/plan/stream", json=plan_payload()) as response:
        "".join(response.iter_text())

    with owned_client.stream("POST", "/api/trip/plan/stream", json=plan_payload()) as response:
        body = "".join(response.iter_text())

    errors = [event["data"] for event in parse_events(body) if event["event"] == "error"]
    assert errors
    assert errors[0]["code"] == 429
    assert "上限" in errors[0]["detail"]


def test_stream_survives_a_generation_failure(owned_client, plan_payload, offline_mode, monkeypatch) -> None:
    from src.api.deps import get_pipeline

    pipeline = get_pipeline()

    async def boom(request, on_event=None):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(pipeline, "run", boom)
    monkeypatch.setattr("src.api.deps.get_pipeline", lambda: pipeline)

    with owned_client.stream("POST", "/api/trip/plan/stream", json=plan_payload()) as response:
        body = "".join(response.iter_text())

    errors = [event["data"] for event in parse_events(body) if event["event"] == "error"]
    assert errors
    assert errors[0]["code"] == 500
