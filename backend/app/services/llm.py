import json

from openai import AsyncOpenAI
from openai import OpenAIError

from app.config import Settings


class LLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = (
            AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url or None,
                timeout=30,
            )
            if settings.has_llm
            else None
        )

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict | None:
        if self.client is None:
            return None

        try:
            response = await self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,
                response_format={"type": "json_object"},
            )
        except OpenAIError:
            return None
        if isinstance(response, str):
            content = response
        else:
            try:
                content = response.choices[0].message.content or "{}"
            except (AttributeError, IndexError):
                return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
