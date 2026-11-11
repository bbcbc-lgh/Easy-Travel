import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from src.model.llm_profile import ModelProfile

logger = logging.getLogger(__name__)


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

    async def complete(self, messages: list[dict[str, str]]) -> LLMCompletion:
        request_kwargs: dict = {}
        if self.profile.max_tokens:
            request_kwargs["max_tokens"] = self.profile.max_tokens
        if self.profile.supports_reasoning_effort and self.profile.reasoning_effort:
            request_kwargs["reasoning_effort"] = self.profile.reasoning_effort

        response = await self.client.chat.completions.create(
            model=self.profile.name,
            messages=messages,
            temperature=0.4,
            response_format={"type": "json_object"},
            **request_kwargs,
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
