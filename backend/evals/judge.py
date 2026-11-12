"""Optional LLM-as-judge pass.

The deterministic metrics answer "is this plan mechanically sound". The judge
answers "does this plan read like a good trip". It is opt-in because each call
costs money and tens of seconds.
"""

import logging

from pydantic import BaseModel, Field

from src.model.schemas import TripPlan
from src.service.llm_gateway import LLMGateway, LLMUnavailableError
from src.service.logging import log_event

logger = logging.getLogger(__name__)

JUDGE_PROMPT_VERSION = "judge-v1"

SYSTEM_PROMPT = (
    "你是资深旅行编辑，负责评审行程质量。只输出 JSON："
    '{"score": 1-5 的整数, "issues": ["具体问题"], "rationale": "一句话理由"}\n'
    "评分标准（5 分制）：\n"
    "5 = 动线顺畅、主题一致、节奏合理、餐饮与预算匹配，可直接出行；\n"
    "4 = 整体合理，有个别小问题；\n"
    "3 = 能用，但存在明显需要人工调整的地方；\n"
    "2 = 结构混乱或明显不符合偏好/预算；\n"
    "1 = 不可用。\n"
    "只评价给定行程，不要补充新地点。issues 最多 3 条，必须具体到第几天。"
)


class JudgeVerdict(BaseModel):
    score: int = Field(..., ge=1, le=5)
    issues: list[str] = Field(default_factory=list)
    rationale: str = ""


def build_plan_summary(plan: TripPlan) -> str:
    lines = [
        f"城市：{plan.city}",
        f"日期：{plan.start_date} 至 {plan.end_date}，共 {len(plan.days)} 天",
        f"预算合计：{plan.budget.total if plan.budget else '未知'} 元",
    ]
    for day in plan.days:
        attractions = "、".join(item.name for item in day.attractions) or "无"
        lines.append(f"第 {day.day_index + 1} 天（{day.date}）：景点 {attractions}；说明：{day.description}")
    return "\n".join(lines)


async def judge_plan(gateway: LLMGateway, plan: TripPlan) -> dict | None:
    user_prompt = build_plan_summary(plan)
    try:
        generation = await gateway.generate_json(
            SYSTEM_PROMPT,
            user_prompt,
            prompt_version=JUDGE_PROMPT_VERSION,
            validate=JudgeVerdict.model_validate,
        )
    except LLMUnavailableError as exc:
        log_event(
            logger,
            "eval.judge_unavailable",
            level=logging.WARNING,
            reason=exc.reason,
            city=plan.city,
        )
        return None

    verdict: JudgeVerdict = generation.value
    return {
        "score": verdict.score,
        "issues": verdict.issues,
        "rationale": verdict.rationale,
        "model": generation.profile,
    }
