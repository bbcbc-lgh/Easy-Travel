from typing import Literal

from pydantic import BaseModel, Field


class ModelProfile(BaseModel):
    """One callable model, described by capability rather than by brand.

    The gateway walks profiles in declaration order, so ``primary`` first and
    ``backup`` afterwards is the fallback chain.
    """

    name: str = Field(..., min_length=1, description="模型名，直接传给服务商")
    tier: Literal["primary", "backup", "fast"] = Field(default="primary", description="档位；primary 先用，backup 兜底")
    base_url: str | None = Field(default=None, description="覆盖全局 LLM_BASE_URL")
    api_key: str | None = Field(default=None, description="覆盖全局 LLM_API_KEY")
    timeout_seconds: float = Field(default=120.0, gt=0, description="单次调用超时（秒）")
    max_tokens: int = Field(default=0, ge=0, description="输出上限；0 表示使用服务商默认值（思考 token 也占此预算）")
    max_retries: int = Field(default=2, ge=0, le=5, description="该模型上的重试次数（不含首次调用）")
    temperature: float = Field(
        default=0.4,
        ge=0.0,
        le=2.0,
        description="采样温度：决策类任务要低，写描述类可以高；0.4 保持历史行为",
    )
    supports_json_schema: bool = Field(default=False, description="是否支持 response_format=json_schema")
    supports_reasoning_effort: bool = Field(default=False, description="是否支持 reasoning_effort")
    reasoning_effort: str | None = Field(default=None, description="调用时携带的 reasoning_effort 值")
