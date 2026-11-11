import json
import logging
from collections.abc import Callable
from datetime import timedelta

from src.model.schemas import (
    Attraction,
    DayPlan,
    Hotel,
    Meal,
    PlanDecision,
    TripPlan,
    TripPlanRequest,
)
from src.planning.budget import calculate_budget
from src.planning.contracts import CandidatePlaces
from src.planning.scheduler import optimise_order, pick_meals
from src.service.llm_gateway import LLMGateway, LLMGeneration
from src.service.logging import log_event

logger = logging.getLogger(__name__)

PROMPT_VERSION = "planner-v4"


class DecisionError(Exception):
    """The model's choices cannot be turned into a grounded itinerary."""


class LLMPlanner:
    """Asks the model *what* to do, then lets the scheduler decide *how*.

    The model only picks names from the candidate lists; order within a day and
    meal selection are deterministic (see ``Scheduler``), so it can neither
    invent places nor produce a zig-zag route.
    """

    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def plan(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None = None,
    ) -> TripPlan:
        generation = await self._generate(request, candidates, feedback)
        return self._hydrate(generation, request, candidates)

    async def _generate(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None,
    ) -> LLMGeneration:
        system_prompt = (
            "你是行程规划专家。只能从用户给出的候选地点中选择，不要编造任何地点。\n"
            '只输出 JSON：{"days":[{"day_index":0,"description":"当日安排与安排理由",'
            '"attractions":["景点名称"],"meals":["餐饮名称"],"hotel":"酒店名称"}],'
            '"overall_suggestions":"整体建议"}\n'
            f"规则：days 必须恰好覆盖 0 到 {request.days - 1}；每天 1-3 个景点，所有景点不得重复；"
            "同一天的景点必须彼此靠近（尽量在 5 公里内），避免跨区折返；"
            "每天安排 3 个餐饮，早餐要选酒店附近的早点类店铺；"
            "description 只写活动、区域和节奏，不要写具体餐厅或酒店名称（餐食与住宿由其他字段决定）；"
            "hotel 只能取候选酒店；不要输出坐标、价格、天气或 Markdown 代码块。"
        )
        weather_summary = [
            f"{item.date} {item.day_weather} {item.night_temp}~{item.day_temp}℃" for item in candidates.weather
        ]
        user_prompt = (
            f"目的地：{request.city}\n"
            f"日期：{request.start_date} 到 {request.end_date}，共 {request.days} 天\n"
            f"偏好：{request.preferences}\n"
            f"预算：{request.budget}\n"
            f"交通：{request.transportation}\n"
            f"住宿：{request.accommodation}\n"
            f"候选景点：{json.dumps([item.name for item in candidates.attractions[:24]], ensure_ascii=False)}\n"
            f"候选酒店：{json.dumps([item.name for item in candidates.hotels[:6]], ensure_ascii=False)}\n"
            f"候选餐饮：{json.dumps([item.name for item in candidates.meals[:12]], ensure_ascii=False)}\n"
            f"天气：{json.dumps(weather_summary, ensure_ascii=False)}\n"
        )
        if feedback:
            user_prompt += "上一版行程存在以下问题，请在本版中修正：\n" + "\n".join(f"- {item}" for item in feedback)

        return await self.gateway.generate_json(
            system_prompt,
            user_prompt,
            prompt_version=PROMPT_VERSION,
            validate=self._build_validator(request, candidates),
        )

    def _build_validator(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
    ) -> Callable[[dict], PlanDecision]:
        attraction_index = _index_by_name(candidates.attractions)
        hotel_index = _index_by_name(candidates.hotels)
        meal_index = _index_by_name(candidates.meals)

        def validate(payload: dict) -> PlanDecision:
            decision = PlanDecision.model_validate(payload)
            if len(decision.days) != request.days:
                raise ValueError(f"days must contain exactly {request.days} entries")
            if sorted(day.day_index for day in decision.days) != list(range(request.days)):
                raise ValueError(f"day_index must cover 0..{request.days - 1} exactly once")
            seen: set[str] = set()
            for day in decision.days:
                if not day.attractions:
                    raise ValueError(f"day {day.day_index} must contain at least one attraction")
                if len(day.attractions) > 3:
                    raise ValueError(f"day {day.day_index} must not contain more than 3 attractions")
                for name in day.attractions:
                    key = _name_key(name)
                    if key not in attraction_index:
                        raise ValueError(f"attraction {name!r} is not in the candidate list")
                    if key in seen:
                        raise ValueError(f"attraction {name!r} is used on more than one day")
                    seen.add(key)
                for name in day.meals:
                    if _name_key(name) not in meal_index:
                        raise ValueError(f"meal {name!r} is not in the candidate list")
                if day.hotel and _name_key(day.hotel) not in hotel_index:
                    raise ValueError(f"hotel {day.hotel!r} is not in the candidate list")
            return decision

        return validate

    def _hydrate(
        self,
        generation: LLMGeneration,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
    ) -> TripPlan:
        decision: PlanDecision = generation.value
        attraction_index = _index_by_name(candidates.attractions)
        hotel_index = _index_by_name(candidates.hotels)
        default_hotel = candidates.hotels[0] if candidates.hotels else None
        decision_by_index = {day.day_index: day for day in decision.days}

        used_meal_keys: set[str] = set()
        days: list[DayPlan] = []
        for day_index in range(request.days):
            selected = decision_by_index.get(day_index)
            if selected is None:
                raise DecisionError(f"day_{day_index}_missing")

            attractions: list[Attraction] = []
            for name in selected.attractions:
                attraction = attraction_index.get(_name_key(name))
                if attraction is None:
                    raise DecisionError(f"unknown_attraction:{name}")
                attractions.append(attraction)

            hotel: Hotel | None = default_hotel
            if selected.hotel:
                hotel = hotel_index.get(_name_key(selected.hotel)) or default_hotel

            ordered = optimise_order(hotel.location if hotel else None, attractions)
            meals: list[Meal] = pick_meals(
                candidates.meals,
                request,
                hotel,
                ordered,
                used_meal_keys,
                preferred=selected.meals,
            )

            days.append(
                DayPlan(
                    date=(request.start_date + timedelta(days=day_index)).isoformat(),
                    day_index=day_index,
                    description=selected.description,
                    transportation=request.transportation,
                    accommodation=request.accommodation,
                    hotel=hotel,
                    attractions=ordered,
                    meals=meals,
                )
            )

        plan = TripPlan(
            city=request.city,
            start_date=request.start_date.isoformat(),
            end_date=request.resolved_end_date.isoformat(),
            days=days,
            weather_info=list(candidates.weather),
            overall_suggestions=decision.overall_suggestions
            or f"建议使用{request.transportation}衔接当天景点，出发前确认开放时间与天气。",
            budget=calculate_budget(days, request),
        )
        log_event(
            logger,
            "planner.completed",
            source="llm",
            prompt_version=PROMPT_VERSION,
            model=generation.profile,
            attempts=generation.attempts,
            repaired=generation.repaired,
            elapsed_ms=generation.elapsed_ms,
            city=request.city,
            days=request.days,
            candidate_attractions=len(candidates.attractions),
        )
        return plan


def _name_key(name: str) -> str:
    return "".join(name.split()).lower()


def _index_by_name(items) -> dict:
    index = {}
    for item in items:
        index.setdefault(_name_key(item.name), item)
    return index
