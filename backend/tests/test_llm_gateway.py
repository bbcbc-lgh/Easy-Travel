import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError
from pydantic import BaseModel, Field

from src.config import Settings
from src.model.llm_profile import ModelProfile
from src.service.llm import LLMClient, LLMCompletion
from src.service.llm_gateway import LLMGateway, LLMUnavailableError


class StubCompletions:
    """Stands in for ``AsyncOpenAI.chat.completions`` so request kwargs are visible."""

    def __init__(self) -> None:
        self.kwargs: dict | None = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(
            content="{}",
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=None,
        )


class FakeClient:
    """One profile's client: returns queued responses and records every call."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []
        self.schemas: list[dict | None] = []

    async def complete(self, messages: list[dict[str, str]], *, schema: dict | None = None) -> LLMCompletion:
        self.calls.append(messages)
        self.schemas.append(schema)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.service.llm_gateway.asyncio.sleep", AsyncMock())


def completion(content: str = '{"ok": true}', finish_reason: str = "stop") -> LLMCompletion:
    return LLMCompletion(
        content=content,
        finish_reason=finish_reason,
        prompt_tokens=100,
        completion_tokens=200,
        reasoning_tokens=150,
    )


def make_gateway(*profiles: dict, total_budget: float = 60.0) -> LLMGateway:
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://example.test",
        use_sample_data=False,
        llm_profiles=[ModelProfile(**profile) for profile in profiles],
        llm_total_budget_seconds=total_budget,
    )
    return LLMGateway(settings)


def inject(gateway: LLMGateway, profile_name: str, client: FakeClient) -> None:
    gateway._clients[profile_name] = client


def timeout_error() -> APITimeoutError:
    return APITimeoutError(request=httpx.Request("POST", "https://example.test"))


def auth_error() -> AuthenticationError:
    request = httpx.Request("POST", "https://example.test")
    return AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)


# --- B2: timeout, retry, truncation -----------------------------------------


def test_default_profile_timeout_is_no_longer_eight_seconds() -> None:
    settings = Settings(llm_api_key="test-key", llm_base_url="https://example.test")

    profile = settings.model_profiles[0]
    assert profile.timeout_seconds >= 60
    assert settings.llm_total_budget_seconds >= settings.llm_timeout_seconds


def test_first_profile_result_is_returned() -> None:
    gateway = make_gateway({"name": "primary-model"})
    client = FakeClient([completion('{"a": 1}')])
    inject(gateway, "primary-model", client)

    result = asyncio.run(gateway.generate_json("system", "user", prompt_version="p"))

    assert result.payload == {"a": 1}
    assert result.profile == "primary-model"
    assert result.attempts == 1
    assert result.repaired is False
    assert len(client.calls) == 1


def test_transient_error_is_retried_then_succeeds() -> None:
    gateway = make_gateway({"name": "primary-model", "max_retries": 2})
    client = FakeClient([timeout_error(), completion('{"a": 2}')])
    inject(gateway, "primary-model", client)

    result = asyncio.run(gateway.generate_json("system", "user", prompt_version="p"))

    assert result.payload == {"a": 2}
    assert result.attempts == 2
    assert len(client.calls) == 2


def test_truncated_output_is_retried() -> None:
    gateway = make_gateway({"name": "primary-model", "max_retries": 1})
    client = FakeClient([completion("", finish_reason="length"), completion('{"a": 3}')])
    inject(gateway, "primary-model", client)

    result = asyncio.run(gateway.generate_json("system", "user", prompt_version="p"))

    assert result.payload == {"a": 3}
    assert result.attempts == 2


# --- B4: profile fallback ----------------------------------------------------


def test_non_retryable_error_moves_to_backup_profile() -> None:
    gateway = make_gateway(
        {"name": "primary-model", "max_retries": 2},
        {"name": "backup-model", "max_retries": 1},
    )
    primary = FakeClient([auth_error()])
    backup = FakeClient([completion('{"from": "backup"}')])
    inject(gateway, "primary-model", primary)
    inject(gateway, "backup-model", backup)

    result = asyncio.run(gateway.generate_json("system", "user", prompt_version="p"))

    assert result.profile == "backup-model"
    assert result.payload == {"from": "backup"}
    assert len(primary.calls) == 1, "auth errors must not be retried"
    assert len(backup.calls) == 1


def test_exhausted_primary_falls_back_to_backup() -> None:
    gateway = make_gateway(
        {"name": "primary-model", "max_retries": 1},
        {"name": "backup-model", "max_retries": 0},
    )
    inject(gateway, "primary-model", FakeClient([timeout_error(), timeout_error()]))
    inject(gateway, "backup-model", FakeClient([completion('{"from": "backup"}')]))

    result = asyncio.run(gateway.generate_json("system", "user", prompt_version="p"))

    assert result.profile == "backup-model"


def test_all_profiles_failing_raises_unavailable_with_reason() -> None:
    gateway = make_gateway({"name": "primary-model", "max_retries": 1})
    inject(gateway, "primary-model", FakeClient([completion("not json"), completion("not json")]))

    with pytest.raises(LLMUnavailableError) as excinfo:
        asyncio.run(gateway.generate_json("system", "user", prompt_version="p"))

    assert excinfo.value.reason == "invalid_json"
    assert excinfo.value.attempts == 2


def test_missing_api_key_raises_disabled() -> None:
    settings = Settings(llm_api_key="", use_sample_data=False)
    gateway = LLMGateway(settings)

    with pytest.raises(LLMUnavailableError) as excinfo:
        asyncio.run(gateway.generate_json("system", "user", prompt_version="p"))

    assert excinfo.value.reason == "llm_disabled"


def test_json_wrapped_in_markdown_is_salvaged() -> None:
    gateway = make_gateway({"name": "primary-model"})
    client = FakeClient([completion('```json\n{"a": 5}\n```')])
    inject(gateway, "primary-model", client)

    result = asyncio.run(gateway.generate_json("system", "user", prompt_version="p"))

    assert result.payload == {"a": 5}
    assert len(client.calls) == 1, "a salvageable answer must not be retried"


def test_json_with_surrounding_prose_is_salvaged() -> None:
    gateway = make_gateway({"name": "primary-model"})
    client = FakeClient([completion('这是行程：\n{"a": 6}\n希望对你有帮助。')])
    inject(gateway, "primary-model", client)

    result = asyncio.run(gateway.generate_json("system", "user", prompt_version="p"))

    assert result.payload == {"a": 6}


# --- B3: schema validation + repair -----------------------------------------


def _validate_city(payload: dict) -> dict:
    if "city" not in payload:
        raise ValueError("city is required")
    return payload


def test_schema_failure_triggers_one_repair_round() -> None:
    gateway = make_gateway({"name": "primary-model", "max_retries": 1})
    client = FakeClient([completion('{"wat": 1}'), completion('{"city": "杭州"}')])
    inject(gateway, "primary-model", client)

    result = asyncio.run(gateway.generate_json("system", "user", prompt_version="p", validate=_validate_city))

    assert result.value == {"city": "杭州"}
    assert result.repaired is True
    assert result.attempts == 2

    repair_messages = client.calls[1]
    assert [message["role"] for message in repair_messages] == ["system", "user", "assistant", "user"]
    assert "city is required" in repair_messages[-1]["content"]
    assert repair_messages[-2]["content"] == '{"wat": 1}'


def test_repair_is_attempted_only_once_per_profile() -> None:
    gateway = make_gateway({"name": "primary-model", "max_retries": 3})
    client = FakeClient([completion('{"wat": 1}'), completion('{"still": "wrong"}')])
    inject(gateway, "primary-model", client)

    with pytest.raises(LLMUnavailableError) as excinfo:
        asyncio.run(gateway.generate_json("system", "user", prompt_version="p", validate=_validate_city))

    assert excinfo.value.reason == "schema_invalid"
    assert len(client.calls) == 2, "a second repair round must not be attempted"


def test_valid_payload_skips_repair() -> None:
    gateway = make_gateway({"name": "primary-model", "max_retries": 2})
    client = FakeClient([completion('{"city": "杭州"}')])
    inject(gateway, "primary-model", client)

    result = asyncio.run(gateway.generate_json("system", "user", prompt_version="p", validate=_validate_city))

    assert result.repaired is False
    assert len(client.calls) == 1


def test_flat_settings_carry_reasoning_effort() -> None:
    profile = Settings(llm_reasoning_effort="minimal").model_profiles[0]

    assert profile.supports_reasoning_effort is True
    assert profile.reasoning_effort == "minimal"


def test_reasoning_effort_is_off_by_default() -> None:
    profile = Settings(llm_reasoning_effort="").model_profiles[0]

    assert profile.supports_reasoning_effort is False
    assert profile.reasoning_effort is None


# --- B1: strict structured output -------------------------------------------


class _City(BaseModel):
    city: str = Field(..., description="城市")
    days: int = Field(default=1, ge=1)


def _structured_gateway(**profile) -> tuple[LLMGateway, FakeClient]:
    gateway = make_gateway({"name": "primary-model", **profile})
    client = FakeClient([completion('{"city": "杭州"}')])
    inject(gateway, "primary-model", client)
    return gateway, client


def test_structured_output_is_off_by_default() -> None:
    """A service without json_schema rejects the request, so it must stay opt-in."""
    gateway, client = _structured_gateway()

    asyncio.run(gateway.generate_json("s", "u", prompt_version="p", response_schema=_City))

    assert client.schemas == [None]


def test_a_profile_that_declares_json_schema_receives_a_strict_schema() -> None:
    gateway, client = _structured_gateway(supports_json_schema=True)

    asyncio.run(gateway.generate_json("s", "u", prompt_version="p", response_schema=_City))

    schema = client.schemas[0]
    assert schema is not None
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["city", "days"]


def test_the_global_switch_enables_it_without_editing_every_profile() -> None:
    settings = Settings(
        llm_api_key="test-key",
        use_sample_data=False,
        llm_json_schema=True,
        llm_profiles=[ModelProfile(name="primary-model")],
    )
    gateway = LLMGateway(settings)
    client = FakeClient([completion('{"city": "杭州"}')])
    inject(gateway, "primary-model", client)

    asyncio.run(gateway.generate_json("s", "u", prompt_version="p", response_schema=_City))

    assert client.schemas[0] is not None


def test_strict_mode_does_not_spend_a_call_on_repair() -> None:
    """The provider already enforced the schema; echoing the error back cannot help."""
    gateway = make_gateway({"name": "primary-model", "max_retries": 2, "supports_json_schema": True})
    client = FakeClient([completion('{"wat": 1}'), completion('{"wat": 2}'), completion('{"wat": 3}')])
    inject(gateway, "primary-model", client)

    with pytest.raises(LLMUnavailableError) as excinfo:
        asyncio.run(gateway.generate_json("s", "u", prompt_version="p", validate=_validate_city, response_schema=_City))

    assert excinfo.value.reason == "schema_invalid"
    assert len(client.calls) == 1, "no repair round in strict mode"


def test_the_schema_is_built_once_per_profile_and_model() -> None:
    gateway, client = _structured_gateway(supports_json_schema=True)
    client.responses = [completion('{"city": "杭州"}'), completion('{"city": "苏州"}')]

    asyncio.run(gateway.generate_json("s", "u", prompt_version="p", response_schema=_City))
    asyncio.run(gateway.generate_json("s", "u", prompt_version="p", response_schema=_City))

    assert len(gateway._schema_cache) == 1
    assert client.schemas[0] is client.schemas[1]


def test_the_client_sends_temperature_and_the_schema_block() -> None:
    client = LLMClient(ModelProfile(name="vendor.model-v1", temperature=0.15), api_key="test-key")
    completions = StubCompletions()
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]

    asyncio.run(client.complete([], schema={"type": "object"}))

    assert completions.kwargs is not None
    assert completions.kwargs["temperature"] == 0.15
    response_format = completions.kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["name"] == "vendor_model-v1"


def test_the_client_falls_back_to_json_object_without_a_schema() -> None:
    client = LLMClient(ModelProfile(name="m"), api_key="test-key")
    completions = StubCompletions()
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]

    asyncio.run(client.complete([]))

    assert completions.kwargs is not None
    assert completions.kwargs["response_format"] == {"type": "json_object"}
    assert completions.kwargs["temperature"] == 0.4
