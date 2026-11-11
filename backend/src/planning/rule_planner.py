import logging
from datetime import timedelta

from src.model.schemas import DayPlan, TripPlan, TripPlanRequest
from src.planning.budget import calculate_budget
from src.planning.contracts import CandidatePlaces
from src.planning.density import DAILY_LOAD_LIMIT, attraction_load
from src.planning.scheduler import build_days, enforce_load, pick_meals
from src.service.logging import log_event

logger = logging.getLogger(__name__)


class RulePlanner:
    """Deterministic planner: geometry decides everything.

    It is the fallback when no model is available, and the baseline the model
    path is measured against.
    """

    async def plan(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None = None,
    ) -> TripPlan:
        hotel = candidates.hotels[0] if candidates.hotels else None
        anchor = hotel.location if hotel else None
        groups = build_days(candidates.attractions, request.days, anchor)
        groups = enforce_load(groups, attraction_load, DAILY_LOAD_LIMIT)

        used_meal_keys: set[str] = set()
        days: list[DayPlan] = []
        for day_index, group in enumerate(groups):
            meals = pick_meals(candidates.meals, request, hotel, group, used_meal_keys)
            if group:
                names = "、".join(item.name for item in group)
                description = f"第 {day_index + 1} 天按距离就近安排 {names}，减少往返，余下时间留给周边慢行。"
            else:
                description = "候选景点不足，今天预留为自由探索和休息。"
            days.append(
                DayPlan(
                    date=(request.start_date + timedelta(days=day_index)).isoformat(),
                    day_index=day_index,
                    description=description,
                    transportation=request.transportation,
                    accommodation=request.accommodation,
                    hotel=hotel,
                    attractions=list(group),
                    meals=meals,
                )
            )

        plan = TripPlan(
            city=request.city,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            days=days,
            weather_info=list(candidates.weather),
            overall_suggestions=(
                f"建议按区域集中游览，使用{request.transportation}衔接；"
                "出发前再次确认开放时间、门票预约和天气变化。"
            ),
            budget=calculate_budget(days, request),
        )
        log_event(
            logger,
            "planner.rules_built",
            city=request.city,
            days=request.days,
            candidate_attractions=len(candidates.attractions),
            feedback_applied=bool(feedback),
        )
        return plan
