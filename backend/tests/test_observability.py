import asyncio
import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APITimeoutError

import src.service.amap as amap_module
from src.agent.planner_agent import PROMPT_VERSION, PlannerAgent
from src.api.main import app
from src.config import Settings
from src.model.llm_profile import ModelProfile
from src.model.schemas import (
    Attraction,
    Hotel,
    Location,
    PlanDecision,
    PlanDecisionDay,
    TripPlanRequest,
)
from src.service.amap import AMapService
from src.service.llm import LLMCompletion
from src.service.llm_gateway import LLMGateway, LLMGeneration, LLMUnavailableError
from src.service.logging import JsonFormatter, log_event, reset_trace_id, set_trace_id

client = TestClient(app)


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def record_events():
    handler = RecordingHandler()
    logger = logging.getLogger("src")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def events(handler: RecordingHandler, name: str) -> list[logging.LogRecord]:
    return [record for record in handler.records if record.getMessage() == name]


def fields(record: logging.LogRecord) -> dict:
    return getattr(record, "fields", {})


def make_request(**overrides) -> TripPlanRequest:
    payload = {
        "city": "杭州",
        "start_date": "2026-11-20",
        "days": 2,
        "preferences": "历史文化",
        "budget": "中等",
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
    }
    payload.update(overrides)
    return TripPlanRequest(**payload)


class FakeClient:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]], *, schema: dict | None = None) -> LLMCompletion:
        self.calls.append(messages)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def gateway_with(client_stub: FakeClient, max_retries: int = 1) -> LLMGateway:
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://example.test",
        use_sample_data=False,
        llm_profiles=[ModelProfile(name="primary-model", max_retries=max_retries)],
    )
    gateway = LLMGateway(settings)
    gateway._clients["primary-model"] = client_stub
    return gateway


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.service.llm_gateway.asyncio.sleep", AsyncMock())


# --- A1: trace id propagation -------------------------------------------------


def test_trace_id_header_is_generated_per_request() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    trace_id = response.headers.get("x-trace-id")
    assert trace_id
    assert len(trace_id) == 16


def test_incoming_request_id_is_reused() -> None:
    response = client.get("/api/health", headers={"X-Request-Id": "abc-123_XYZ"})

    assert response.headers["x-trace-id"] == "abc-123_XYZ"


def test_incoming_request_id_is_sanitized() -> None:
    response = client.get("/api/health", headers={"X-Request-Id": "bad id<script>"})

    assert response.headers["x-trace-id"] == "badidscript"


def test_request_log_carries_trace_id_fields() -> None:
    with record_events() as handler:
        client.get("/api/health")

    requests = events(handler, "http.request")
    assert requests, "expected an http.request event"
    logged = fields(requests[0])
    assert logged["path"] == "/api/health"
    assert logged["status_code"] == 200
    assert "elapsed_ms" in logged


def test_json_formatter_emits_trace_id_and_fields() -> None:
    token = set_trace_id("trace-json-1")
    try:
        record = logging.LogRecord("src.test", logging.INFO, __file__, 1, "llm.completed", (), None)
        record.fields = {"model": "deepseek-flash", "completion_tokens": 42}
        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_trace_id(token)

    assert payload["trace_id"] == "trace-json-1"
    assert payload["event"] == "llm.completed"
    assert payload["model"] == "deepseek-flash"
    assert payload["completion_tokens"] == 42
    assert payload["level"] == "INFO"


def test_log_event_truncates_long_fields() -> None:
    with record_events() as handler:
        log_event(logging.getLogger("src.test"), "test.long", payload="x" * 1000)

    record = events(handler, "test.long")[0]
    assert fields(record)["payload"].endswith("...")
    assert len(fields(record)["payload"]) == 303


# --- A3 / B: model calls become visible --------------------------------------


def test_llm_completion_logs_tokens_and_finish_reason() -> None:
    completion = LLMCompletion(
        content='{"city": "杭州"}',
        finish_reason="stop",
        prompt_tokens=120,
        completion_tokens=300,
        reasoning_tokens=250,
    )
    gateway = gateway_with(FakeClient([completion]))

    with record_events() as handler:
        result = asyncio.run(gateway.generate_json("system", "user", prompt_version=PROMPT_VERSION))

    assert result.payload == {"city": "杭州"}
    completed = events(handler, "llm.completed")
    assert completed, "expected an llm.completed event"
    logged = fields(completed[0])
    assert logged["profile"] == "primary-model"
    assert logged["completion_tokens"] == 300
    assert logged["reasoning_tokens"] == 250
    assert logged["finish_reason"] == "stop"
    assert logged["attempts"] == 1
    assert logged["repaired"] is False


def test_llm_failure_is_logged_per_attempt() -> None:
    timeout = APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    gateway = gateway_with(FakeClient([timeout, timeout]), max_retries=1)

    with record_events() as handler:
        with pytest.raises(LLMUnavailableError) as excinfo:
            asyncio.run(gateway.generate_json("system", "user", prompt_version=PROMPT_VERSION))

    assert excinfo.value.reason == "provider_timeout"
    failed = events(handler, "llm.attempt_failed")
    assert len(failed) == 2
    assert fields(failed[0])["reason"] == "provider_timeout"
    assert fields(failed[0])["profile"] == "primary-model"
    assert fields(failed[0])["retryable"] is True
    assert events(handler, "llm.profile_exhausted")


# --- planner: model choices vs rule fallback ---------------------------------


class UnavailableGateway:
    async def generate_json(self, *args, **kwargs):
        raise LLMUnavailableError("provider_timeout", attempts=3)


def test_planner_logs_degraded_reason_when_llm_is_unavailable() -> None:
    agent = PlannerAgent(UnavailableGateway())

    with record_events() as handler:
        plan = asyncio.run(agent.run(make_request(), [], [], [], None))

    assert plan.days
    degraded = events(handler, "planner.degraded")
    assert degraded, "expected a planner.degraded event"
    logged = fields(degraded[0])
    assert logged["reason"] == "llm_provider_timeout"
    assert logged["source"] == "rule_fallback"
    assert logged["city"] == "杭州"
    assert fields(events(handler, "llm.unavailable")[0])["attempts"] == 3


def test_planner_logs_model_provenance_on_success() -> None:
    attraction = Attraction(
        name="浙江省博物馆",
        address="杭州市西湖区",
        location=Location(longitude=120.155, latitude=30.274),
        ticket_price=0,
        source="amap",
    )
    hotel = Hotel(name="杭州测试酒店", address="杭州市上城区", estimated_cost=300, source="amap")
    decision = PlanDecision(
        days=[
            PlanDecisionDay(
                day_index=0,
                description="上午博物馆，下午湖边慢行。",
                attractions=["浙江省博物馆"],
                hotel="杭州测试酒店",
            )
        ],
        overall_suggestions="按区域安排，减少折返。",
    )

    class OkGateway:
        # Single-phase, because this test asserts the model's own day prose reaches
        # the plan; two-phase writes prose in a second call that never happens here.
        settings = SimpleNamespace(plan_two_phase=False)

        async def generate_json(self, *args, **kwargs):
            return LLMGeneration(
                payload={},
                value=decision,
                profile="deepseek-flash",
                attempts=2,
                repaired=True,
                elapsed_ms=123.4,
            )

    with record_events() as handler:
        plan = asyncio.run(PlannerAgent(OkGateway()).run(make_request(days=1), [attraction], [hotel], []))

    completed = events(handler, "planner.completed")
    assert completed, "expected a planner.completed event"
    logged = fields(completed[0])
    assert logged["source"] == "llm"
    assert logged["model"] == "deepseek-flash"
    assert logged["attempts"] == 2
    assert logged["repaired"] is True

    # The model only chose names; every fact comes from the data layer.
    assert plan.days[0].description == "上午博物馆，下午湖边慢行。"
    assert plan.days[0].attractions[0].location.longitude == 120.155
    # Meals are no longer planned; the day is about where to go.
    assert plan.overall_suggestions == "按区域安排，减少折返。"


def test_weather_failure_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info) -> bool:
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("network down")

    monkeypatch.setattr(amap_module.httpx, "AsyncClient", BrokenClient)
    service = AMapService(Settings(use_sample_data=False))

    with record_events() as handler:
        weather = asyncio.run(service.query_weather(make_request()))

    assert len(weather) == 2
    assert all(not item.forecast_available for item in weather)
    unavailable = events(handler, "weather.unavailable")
    assert unavailable, "expected a weather.unavailable event"
    assert fields(unavailable[0])["city"] == "杭州"


# --- A2: effective configuration ---------------------------------------------


def test_describe_hides_secrets() -> None:
    settings = Settings(llm_api_key="secret-key-value", amap_web_service_key="amap-secret-key")
    described = settings.describe()

    serialized = json.dumps(described, ensure_ascii=False)
    assert "secret-key-value" not in serialized
    assert "amap-secret-key" not in serialized
    assert described["llm.api_key_set"] is True
    assert described["llm.api_key_length"] == len("secret-key-value")
    assert described["amap.web_key_set"] is True
    assert "llm.profiles" in described


def test_describe_lists_fallback_chain() -> None:
    settings = Settings(
        llm_api_key="test-key",
        llm_profiles=[
            ModelProfile(name="primary-model", tier="primary"),
            ModelProfile(name="backup-model", tier="backup", timeout_seconds=180),
        ],
    )

    described = settings.describe()

    assert "primary-model(tier=primary" in described["llm.profiles"]
    assert "backup-model(tier=backup" in described["llm.profiles"]


def test_startup_logs_effective_config() -> None:
    with record_events() as handler:
        with TestClient(app):
            pass

    startup = events(handler, "app.startup")
    assert startup, "expected an app.startup event"
    logged = fields(startup[0])
    assert "llm.profiles" in logged
    assert "llm.total_budget_seconds" in logged
    assert "amap.enabled" in logged
    assert "sample_data" in logged


def test_log_fields_redact_api_keys() -> None:
    from src.service.logging import redact_secrets

    text = (
        "Client error '403 Forbidden' for url "
        "'https://devapi.qweather.com/v7/weather/7d?location=1,2&key=abcd1234&lang=zh'"
    )

    redacted = redact_secrets(text)

    assert "abcd1234" not in redacted
    assert "key=***" in redacted


def test_log_event_redacts_keys_in_fields() -> None:
    with record_events() as handler:
        log_event(
            logging.getLogger("src.test"),
            "test.redaction",
            error="GET https://api.example.com/v1?key=SECRET123&x=1 failed",
        )

    record = events(handler, "test.redaction")[0]
    assert "SECRET123" not in fields(record)["error"]
