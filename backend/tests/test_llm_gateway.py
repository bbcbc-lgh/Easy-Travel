import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError

from src.config import Settings
from src.model.llm_profile import ModelProfile
from src.service.llm import LLMCompletion
from src.service.llm_gateway import LLMGateway, LLMUnavailableError


class FakeClient:
    """One profile's client: returns queued responses and records every call."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> LLMCompletion:
        self.calls.append(messages)
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

    result = asyncio.run(
        gateway.generate_json("system", "user", prompt_version="p", validate=_validate_city)
    )

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

    result = asyncio.run(
        gateway.generate_json("system", "user", prompt_version="p", validate=_validate_city)
    )

    assert result.repaired is False
    assert len(client.calls) == 1
