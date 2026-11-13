"""Resilient model access: profile fallback, retries and output repair.

``LLMGateway.generate_json`` is the only entry point the agents use. It hides
everything that must never leak into business code:

* which model profile is being called, and which one to fall back to;
* retry policy for transient failures and for unusable output;
* one schema-repair round when the model returns JSON that fails validation;
* a total time budget across all profiles.
"""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from src.config import Settings
from src.model.jsonschema import strict_json_schema
from src.model.llm_profile import ModelProfile
from src.service.llm import LLMClient, LLMCompletion
from src.service.logging import log_event

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)

_REPAIR_INSTRUCTION = (
    "上一次输出不符合要求：{error}。请只输出修正后的完整 JSON，不要输出解释、Markdown 代码块或任何多余文字。"
)


class LLMUnavailableError(Exception):
    """Raised when every profile has been exhausted."""

    def __init__(self, reason: str, attempts: int = 0, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.attempts = attempts
        #: The last schema complaint, when the reason is ``schema_invalid``. The
        #: planner reads it to learn *which* place it did not have, which is what
        #: makes a bounded "go and find it" retry possible.
        self.detail = detail


@dataclass(slots=True)
class LLMGeneration:
    payload: dict[str, Any]
    value: Any
    profile: str
    attempts: int
    repaired: bool
    elapsed_ms: float


class LLMGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.profiles: list[ModelProfile] = settings.model_profiles
        self._clients: dict[str, LLMClient] = {}
        self._schema_cache: dict[tuple[str, str], dict] = {}

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        prompt_version: str,
        validate: Callable[[dict], Any] | None = None,
        response_schema: type[BaseModel] | None = None,
        budget_seconds: float | None = None,
    ) -> LLMGeneration:
        """One JSON answer, from the first profile that can produce a usable one.

        ``response_schema`` asks for provider-enforced structured output when the
        profile (or ``LLM_JSON_SCHEMA``) says the service supports it. Without it
        the request falls back to ``json_object``, which only promises "this is
        JSON" - the reason a repair round exists at all.
        """
        if not self.settings.has_llm or not self.profiles:
            raise LLMUnavailableError("llm_disabled")

        base_messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        generation_started = perf_counter()
        deadline = generation_started + (
            budget_seconds if budget_seconds is not None else self.settings.llm_total_budget_seconds
        )
        reasons: list[str] = []
        total_attempts = 0
        last_detail = ""

        for profile in self.profiles:
            messages = base_messages
            repaired = False
            attempt = 0
            schema = self._schema_for(profile, response_schema)
            while attempt < profile.max_retries + 1:
                attempt += 1
                total_attempts += 1
                if perf_counter() >= deadline:
                    reasons.append("budget_exhausted")
                    break

                try:
                    completion = await self._attempt(
                        profile=profile,
                        attempt=attempt,
                        messages=messages,
                        prompt_version=prompt_version,
                        reasons=reasons,
                        schema=schema,
                    )
                except _ProfileUnusable:
                    break
                if completion is None:
                    await self._backoff(attempt, deadline)
                    continue

                payload, reason = _parse_payload(completion)
                if payload is None:
                    reasons.append(reason)
                    log_event(
                        logger,
                        "llm.output_rejected",
                        level=logging.WARNING,
                        profile=profile.name,
                        attempt=attempt,
                        reason=reason,
                        finish_reason=completion.finish_reason,
                        content_chars=len(completion.content),
                        completion_tokens=completion.completion_tokens,
                        reasoning_tokens=completion.reasoning_tokens,
                    )
                    await self._backoff(attempt, deadline)
                    continue

                if validate is not None:
                    try:
                        value = validate(payload)
                    except Exception as exc:  # noqa: BLE001 - schema rejection drives the repair round
                        reasons.append("schema_invalid")
                        last_detail = str(exc)[:300]
                        log_event(
                            logger,
                            "llm.validation_failed",
                            level=logging.WARNING,
                            profile=profile.name,
                            attempt=attempt,
                            reason="schema_invalid",
                            error_type=type(exc).__name__,
                            error=str(exc),
                        )
                        if repaired or schema is not None:
                            # With the schema enforced by the provider, a rejection
                            # means our schema is wrong, so echoing the error back
                            # cannot help - it only costs another call.
                            break
                        repaired = True
                        messages = _repair_messages(system_prompt, user_prompt, completion.content, str(exc))
                        log_event(
                            logger,
                            "llm.repair",
                            profile=profile.name,
                            attempt=attempt,
                            prompt_version=prompt_version,
                        )
                        continue
                else:
                    value = payload

                elapsed_ms = round((perf_counter() - generation_started) * 1000, 1)
                log_event(
                    logger,
                    "llm.completed",
                    profile=profile.name,
                    prompt_version=prompt_version,
                    attempts=attempt,
                    repaired=repaired,
                    finish_reason=completion.finish_reason,
                    prompt_tokens=completion.prompt_tokens,
                    completion_tokens=completion.completion_tokens,
                    reasoning_tokens=completion.reasoning_tokens,
                    content_chars=len(completion.content),
                    elapsed_ms=elapsed_ms,
                )
                return LLMGeneration(
                    payload=payload,
                    value=value,
                    profile=profile.name,
                    attempts=attempt,
                    repaired=repaired,
                    elapsed_ms=elapsed_ms,
                )

            log_event(
                logger,
                "llm.profile_exhausted",
                level=logging.WARNING,
                profile=profile.name,
                attempts=attempt,
                reason=reasons[-1] if reasons else "unknown",
            )

        raise LLMUnavailableError(
            reasons[-1] if reasons else "no_profile",
            attempts=total_attempts,
            detail=last_detail,
        )

    async def generate_json_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        prompt_version: str,
        validate: Callable[[dict], Any] | None = None,
        response_schema: type[BaseModel] | None = None,
        budget_seconds: float | None = None,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMGeneration:
        """One streamed call on the primary profile.

        Deliberately single-attempt: this path exists for the description phase,
        where the user is already watching the page and a silent 30-second retry
        helps nobody. The caller falls back to a plain sentence, not a replan.
        """
        if not self.settings.has_llm or not self.profiles:
            raise LLMUnavailableError("llm_disabled")

        profile = self.profiles[0]
        schema = self._schema_for(profile, response_schema)
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        started = perf_counter()
        try:
            completion = await self._client(profile).stream(messages, on_delta=on_delta, schema=schema)
        except APIStatusError as exc:
            log_event(
                logger,
                "llm.stream_failed",
                level=logging.WARNING,
                profile=profile.name,
                reason=f"http_{exc.status_code}",
                error=str(exc),
            )
            raise LLMUnavailableError(f"http_{exc.status_code}", attempts=1) from exc
        except Exception as exc:  # noqa: BLE001 - any transport failure means "no prose"
            log_event(
                logger,
                "llm.stream_failed",
                level=logging.WARNING,
                profile=profile.name,
                reason=type(exc).__name__,
                error=str(exc),
            )
            raise LLMUnavailableError("stream_failed", attempts=1) from exc

        payload, reason = _parse_payload(completion)
        if payload is None:
            raise LLMUnavailableError(reason, attempts=1)

        value: Any = payload
        if validate is not None:
            try:
                value = validate(payload)
            except Exception as exc:  # noqa: BLE001 - a bad description is a fallback, not a crash
                log_event(
                    logger,
                    "llm.stream_validation_failed",
                    level=logging.WARNING,
                    profile=profile.name,
                    reason="schema_invalid",
                    error=str(exc),
                )
                raise LLMUnavailableError("schema_invalid", attempts=1) from exc

        elapsed_ms = round((perf_counter() - started) * 1000, 1)
        log_event(
            logger,
            "llm.streamed",
            profile=profile.name,
            prompt_version=prompt_version,
            content_chars=len(completion.content),
            elapsed_ms=elapsed_ms,
        )
        return LLMGeneration(
            payload=payload,
            value=value,
            profile=profile.name,
            attempts=1,
            repaired=False,
            elapsed_ms=elapsed_ms,
        )

    async def _attempt(
        self,
        *,
        profile: ModelProfile,
        attempt: int,
        messages: list[ChatCompletionMessageParam],
        prompt_version: str,
        reasons: list[str],
        schema: dict | None = None,
    ) -> LLMCompletion | None:
        log_event(
            logger,
            "llm.attempt",
            level=logging.DEBUG,
            profile=profile.name,
            attempt=attempt,
            prompt_version=prompt_version,
            structured=schema is not None,
        )
        started = perf_counter()
        try:
            return await self._client(profile).complete(messages, schema=schema)
        except RETRYABLE_ERRORS as exc:
            reason = _transport_reason(exc)
            reasons.append(reason)
            log_event(
                logger,
                "llm.attempt_failed",
                level=logging.WARNING,
                profile=profile.name,
                attempt=attempt,
                reason=reason,
                retryable=True,
                error_type=type(exc).__name__,
                elapsed_ms=round((perf_counter() - started) * 1000, 1),
                error=str(exc),
            )
            return None
        except APIStatusError as exc:
            reason = f"http_{exc.status_code}"
            reasons.append(reason)
            log_event(
                logger,
                "llm.attempt_failed",
                level=logging.ERROR,
                profile=profile.name,
                attempt=attempt,
                reason=reason,
                retryable=False,
                error_type=type(exc).__name__,
                elapsed_ms=round((perf_counter() - started) * 1000, 1),
                error=str(exc),
            )
            raise _ProfileUnusable(reason) from exc
        except Exception as exc:  # noqa: BLE001 - unknown client failures are not retried blindly
            reason = "unexpected_error"
            reasons.append(reason)
            log_event(
                logger,
                "llm.attempt_failed",
                level=logging.ERROR,
                profile=profile.name,
                attempt=attempt,
                reason=reason,
                retryable=False,
                error_type=type(exc).__name__,
                elapsed_ms=round((perf_counter() - started) * 1000, 1),
                error=str(exc),
                exc_info=True,
            )
            raise _ProfileUnusable(reason) from exc

    def _schema_for(self, profile: ModelProfile, response_schema: type[BaseModel] | None) -> dict | None:
        """The strict schema for this profile, or ``None`` to fall back to json_object."""
        if response_schema is None:
            return None
        if not (self.settings.llm_json_schema or profile.supports_json_schema):
            return None
        key = (profile.name, response_schema.__name__)
        cached = self._schema_cache.get(key)
        if cached is None:
            cached = strict_json_schema(response_schema)
            self._schema_cache[key] = cached
        return cached

    def _client(self, profile: ModelProfile) -> LLMClient:
        client = self._clients.get(profile.name)
        if client is None:
            client = LLMClient(profile, api_key=self.settings.llm_api_key, base_url=self.settings.llm_base_url)
            self._clients[profile.name] = client
        return client

    @staticmethod
    async def _backoff(attempt: int, deadline: float) -> None:
        remaining = deadline - perf_counter()
        if remaining <= 0:
            return
        delay = min(0.5 * 2 ** (attempt - 1), 4.0) + random.uniform(0, 0.25)
        await asyncio.sleep(min(delay, remaining))


class _ProfileUnusable(Exception):
    """Internal marker: stop retrying this profile and move to the next one."""


def _parse_payload(completion: LLMCompletion) -> tuple[dict[str, Any] | None, str]:
    if completion.finish_reason == "length":
        return None, "truncated"
    if not completion.content.strip():
        return None, "empty_content"
    payload = _loads_object(completion.content)
    if payload is None:
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "not_an_object"
    return payload, "ok"


def _loads_object(content: str) -> Any | None:
    """Parse JSON, salvaging the common `````json ... ````` and prose-wrapped replies.

    A full retry costs tens of seconds, so it is worth trying to extract the
    object the model clearly produced before declaring the output unusable.
    """
    text = content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        try:
            return json.loads("\n".join(lines).strip())
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _repair_messages(
    system_prompt: str,
    user_prompt: str,
    previous_content: str,
    error: str,
) -> list[ChatCompletionMessageParam]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": previous_content[:4000]},
        {"role": "user", "content": _REPAIR_INSTRUCTION.format(error=error[:800])},
    ]


def _transport_reason(exc: Exception) -> str:
    if isinstance(exc, APITimeoutError):
        return "provider_timeout"
    if isinstance(exc, RateLimitError):
        return "rate_limited"
    if isinstance(exc, APIConnectionError):
        return "provider_connection"
    if isinstance(exc, InternalServerError):
        return "provider_error_5xx"
    return "provider_error"
