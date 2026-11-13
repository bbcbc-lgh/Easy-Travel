import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from src.model.llm_profile import ModelProfile

logger = logging.getLogger(__name__)

#: `json_schema.name` must match [a-zA-Z0-9_-]+, and model ids contain dots.
_SCHEMA_NAME = re.compile(r"[^A-Za-z0-9_-]")


@dataclass(slots=True)
class LLMCompletion:
    content: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None


class LLMClient:
    """One model profile, one attempt.

    Retries, profile fallback and output repair belong to ``LLMGateway``; keeping
    this class single-shot is what makes the gateway's attempt accounting honest.
    """

    def __init__(self, profile: ModelProfile, api_key: str = "", base_url: str = ""):
        self.profile = profile
        self.client = AsyncOpenAI(
            api_key=profile.api_key or api_key,
            base_url=profile.base_url or base_url or None,
            timeout=profile.timeout_seconds,
            max_retries=0,
        )

    def _request_kwargs(self, schema: dict | None) -> dict:
        request_kwargs: dict = {"temperature": self.profile.temperature}
        if self.profile.max_tokens:
            request_kwargs["max_tokens"] = self.profile.max_tokens
        if self.profile.supports_reasoning_effort and self.profile.reasoning_effort:
            request_kwargs["reasoning_effort"] = self.profile.reasoning_effort
        if schema is not None:
            request_kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": _SCHEMA_NAME.sub("_", self.profile.name),
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            request_kwargs["response_format"] = {"type": "json_object"}
        return request_kwargs

    async def complete(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        schema: dict | None = None,
    ) -> LLMCompletion:
        """One call. ``schema`` asks the provider to enforce structured output."""
        response = await self.client.chat.completions.create(
            model=self.profile.name,
            messages=messages,
            **self._request_kwargs(schema),
        )
        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        return LLMCompletion(
            content=choice.message.content or "",
            finish_reason=getattr(choice, "finish_reason", None),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            reasoning_tokens=getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None),
        )

    async def stream(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
        schema: dict | None = None,
    ) -> LLMCompletion:
        """Same request, delivered as it is generated.

        Used only by the description phase, where the text is the product and the
        user is already staring at the page. Usage numbers are not collected here:
        provider support for ``stream_options`` varies, and this path exists for
        perceived latency, not accounting.
        """
        request_kwargs = {**self._request_kwargs(schema), "stream": True}
        stream = await self.client.chat.completions.create(
            model=self.profile.name,
            messages=messages,
            **request_kwargs,
        )
        parts: list[str] = []
        finish_reason: str | None = None
        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = getattr(choice, "finish_reason", None) or finish_reason
            delta = getattr(choice, "delta", None)
            text = getattr(delta, "content", None) if delta is not None else None
            if not text:
                continue
            parts.append(text)
            if on_delta is not None:
                await on_delta(text)
        return LLMCompletion(content="".join(parts), finish_reason=finish_reason)
