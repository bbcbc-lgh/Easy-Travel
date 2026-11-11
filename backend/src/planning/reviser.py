"""Conversational edits: the model proposes a patch, the server applies it.

The model never returns a full itinerary. It returns *changes* — which places to
drop or add on which day — and every derived field (order, meals, budget,
routes, score) is recomputed here from the data layer.
"""

import json
import logging

from src.model.schemas import DayEdit, DayPlan, PlanPatch, TripPlan, TripPlanRequest
from src.planning.budget import calculate_budget
from src.planning.contracts import CandidatePlaces
from src.planning.notices import attach_data_notices
from src.planning.scheduler import optimise_order, pick_meals
from src.service.llm_gateway import LLMGateway
from src.service.logging import log_event

logger = logging.getLogger(__name__)

PROMPT_VERSION = "reviser-v1"


class PatchError(Exception):
    """The proposed patch cannot be applied to this plan."""


class PlanReviser:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def propose(
        self,
        request: TripPlanRequest,
        plan: TripPlan,
        candidates: CandidatePlaces,
        instruction: str,
    ) -> PlanPatch:
        generation = await self.gateway.generate_json(
            _system_prompt(),
            _user_prompt(request, plan, candidates, instruction),
            prompt_version=PROMPT_VERSION,
            validate=_build_validator(plan, candidates),
        )
        patch: PlanPatch = generation.value
        log_event(
            logger,
            "plan.patch_proposed",
            prompt_version=PROMPT_VERSION,
            city=plan.city,
            changed_days=len(patch.days),
            model=generation.profile,
        )
        return patch

    def apply(
        self,
        plan: TripPlan,
        patch: PlanPatch,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
    ) -> TripPlan:
        attraction_index = _index([*candidates.attractions, *[item for day in plan.days for item in day.attractions]])
        hotel_index = _index([*candidates.hotels, *[day.hotel for day in plan.days if day.hotel]])
        meal_candidates = candidates.meals or [meal for day in plan.days for meal in day.meals]
        edits: dict[int, DayEdit] = {edit.day_index: edit for edit in patch.days}
        used_meal_keys: set[str] = set()

        days: list[DayPlan] = []
        for day in plan.days:
            edit = edits.get(day.day_index)
            attractions = list(day.attractions)
            hotel = day.hotel

            if edit is not None:
                if edit.remove_attractions:
                    removed = {_name_key(name) for name in edit.remove_attractions}
                    attractions = [item for item in attractions if _name_key(item.name) not in removed]
                for name in edit.add_attractions:
                    key = _name_key(name)
                    if any(_name_key(item.name) == key for item in attractions):
                        continue
                    resolved = attraction_index.get(key)
                    if resolved is None:
                        raise PatchError(f"unknown_attraction:{name}")
                    attractions.append(resolved)
                if edit.hotel:
                    resolved_hotel = hotel_index.get(_name_key(edit.hotel))
                    if resolved_hotel is None:
                        raise PatchError(f"unknown_hotel:{edit.hotel}")
                    hotel = resolved_hotel

            if not attractions:
                raise PatchError(f"day_{day.day_index}_would_be_empty")

            ordered = optimise_order(hotel.location if hotel else None, attractions)

            meals = day.meals
            if edit is not None and edit.meals is not None:
                meals = pick_meals(
                    meal_candidates,
                    request,
                    hotel,
                    ordered,
                    used_meal_keys,
                    preferred=edit.meals,
                )
                if not meals:
                    raise PatchError(f"day_{day.day_index}_meals_unavailable")
            else:
                used_meal_keys.update(_name_key(meal.name) for meal in meals)

            days.append(
                DayPlan(
                    date=day.date,
                    day_index=day.day_index,
                    description=(edit.description if edit and edit.description else day.description),
                    transportation=day.transportation,
                    accommodation=day.accommodation,
                    hotel=hotel,
                    attractions=ordered,
                    meals=meals,
                    routes=[],
                )
            )

        revised = TripPlan(
            id=plan.id,
            city=plan.city,
            start_date=plan.start_date,
            end_date=plan.end_date,
            days=days,
            weather_info=plan.weather_info,
            overall_suggestions=patch.overall_suggestions or plan.overall_suggestions,
            degraded=plan.degraded,
            degraded_reason=plan.degraded_reason,
        )
        revised.budget = calculate_budget(days, request)
        return attach_data_notices(revised)


def _system_prompt() -> str:
    return (
        "你是行程编辑助手。用户会对现有行程提出修改要求，你只输出需要变化的字段。\n"
        '只输出 JSON：{"days":[{"day_index":0,"remove_attractions":["景点名"],'
        '"add_attractions":["景点名"],"description":"新的当日说明","meals":["餐饮名"],'
        '"hotel":"酒店名"}],"overall_suggestions":"整体建议","reply":"一句话说明改了什么"}\n'
        "规则：\n"
        "1. 只列出需要改动的天，没提到的天不要出现；\n"
        "2. remove_attractions 必须来自当前行程，add_attractions 必须来自候选景点；\n"
        "3. meals / hotel 如不修改则省略该字段；meals 只能取候选餐饮；\n"
        "4. 每天最终保留 1-3 个景点，不要全部删掉；\n"
        "5. 不要输出坐标、价格或 Markdown；reply 用中文，不超过 40 字。"
    )


def _user_prompt(
    request: TripPlanRequest,
    plan: TripPlan,
    candidates: CandidatePlaces,
    instruction: str,
) -> str:
    lines = [
        f"城市：{plan.city}",
        f"行程天数：{len(plan.days)}",
        f"预算档位：{request.budget}",
        f"交通：{request.transportation}",
        f"住宿偏好：{request.accommodation}",
        f"偏好：{request.preferences}",
        f"用户要求：{instruction}",
        "",
        "当前行程：",
    ]
    for day in plan.days:
        attractions = "、".join(item.name for item in day.attractions) or "无"
        meals = "、".join(f"{meal.type}:{meal.name}" for meal in day.meals) or "无"
        hotel = day.hotel.name if day.hotel else "无"
        lines.append(
            f"- 第 {day.day_index + 1} 天（{day.date}）：景点 {attractions}；餐饮 {meals}；酒店 {hotel}"
        )
    lines += [
        "",
        f"候选景点：{json.dumps([item.name for item in candidates.attractions[:24]], ensure_ascii=False)}",
        f"候选餐饮：{json.dumps([item.name for item in candidates.meals[:12]], ensure_ascii=False)}",
        f"候选酒店：{json.dumps([item.name for item in candidates.hotels[:6]], ensure_ascii=False)}",
    ]
    return "\n".join(lines)


def _build_validator(plan: TripPlan, candidates: CandidatePlaces):
    current_attractions = {_name_key(item.name) for day in plan.days for item in day.attractions}
    candidate_attractions = {_name_key(item.name) for item in candidates.attractions}
    meal_names = {_name_key(item.name) for item in candidates.meals} | {
        _name_key(meal.name) for day in plan.days for meal in day.meals
    }
    hotel_names = {_name_key(item.name) for item in candidates.hotels} | {
        _name_key(day.hotel.name) for day in plan.days if day.hotel
    }

    def validate(payload: dict) -> PlanPatch:
        patch = PlanPatch.model_validate(payload)
        if not patch.days and not patch.overall_suggestions:
            raise ValueError("patch must change at least one day or the overall suggestions")

        seen: set[int] = set()
        for edit in patch.days:
            if edit.day_index >= len(plan.days):
                raise ValueError(f"day_index {edit.day_index} is out of range")
            if edit.day_index in seen:
                raise ValueError(f"day_index {edit.day_index} appears more than once")
            seen.add(edit.day_index)

            for name in edit.remove_attractions:
                if _name_key(name) not in current_attractions:
                    raise ValueError(f"cannot remove {name!r}: not in the current plan")
            for name in edit.add_attractions:
                if _name_key(name) not in candidate_attractions:
                    raise ValueError(f"cannot add {name!r}: not in the candidate list")
            for name in edit.meals or []:
                if _name_key(name) not in meal_names:
                    raise ValueError(f"meal {name!r} is not in the candidate list")
            if edit.hotel and _name_key(edit.hotel) not in hotel_names:
                raise ValueError(f"hotel {edit.hotel!r} is not in the candidate list")
        return patch

    return validate


def _name_key(name: str) -> str:
    return "".join(name.split()).lower()


def _index(items) -> dict:
    index = {}
    for item in items:
        if item is None:
            continue
        index.setdefault(_name_key(item.name), item)
    return index
