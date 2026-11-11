import logging

from src.model.schemas import Attraction, Budget, DayPlan, Hotel, Meal, TripPlan, TripPlanRequest, WeatherInfo
from src.planning.budget import calculate_budget
from src.planning.contracts import CandidatePlaces
from src.planning.llm_planner import PROMPT_VERSION, DecisionError, LLMPlanner
from src.planning.rule_planner import RulePlanner
from src.service.llm_gateway import LLMGateway, LLMUnavailableError
from src.service.logging import log_event
from src.service.sample_data import sample_meals

logger = logging.getLogger(__name__)

__all__ = ["PlannerAgent", "PROMPT_VERSION"]


class PlannerAgent:
    """Orchestrates planning: model first, deterministic geometry as fallback."""

    def __init__(self, llm_gateway: LLMGateway):
        self.llm_planner = LLMPlanner(llm_gateway)
        self.rule_planner = RulePlanner()

    async def run(
        self,
        request: TripPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
        weather_info: list[WeatherInfo],
        meals: list[Meal] | None = None,
        feedback: list[str] | None = None,
    ) -> TripPlan:
        candidates = CandidatePlaces(
            attractions=attractions,
            hotels=hotels,
            meals=meals or sample_meals(request.city, request.budget),
            weather=weather_info,
        )

        try:
            plan = await self.llm_planner.plan(request, candidates, feedback)
        except LLMUnavailableError as exc:
            log_event(
                logger,
                "llm.unavailable",
                level=logging.WARNING,
                reason=exc.reason,
                attempts=exc.attempts,
                prompt_version=PROMPT_VERSION,
            )
            reason = exc.reason if exc.reason.startswith("llm_") else f"llm_{exc.reason}"
        except DecisionError as exc:
            reason = str(exc)
            log_event(
                logger,
                "planner.hydration_failed",
                level=logging.WARNING,
                reason=reason,
                prompt_version=PROMPT_VERSION,
            )
        else:
            plan.degraded = False
            plan.degraded_reason = None
            return self._attach_data_notices(plan)

        log_event(
            logger,
            "planner.degraded",
            level=logging.WARNING,
            reason=reason,
            source="rule_fallback",
            prompt_version=PROMPT_VERSION,
            city=request.city,
            days=request.days,
            candidate_attractions=len(candidates.attractions),
            candidate_hotels=len(candidates.hotels),
            candidate_meals=len(candidates.meals),
        )
        fallback = await self.rule_planner.plan(request, candidates, feedback)
        fallback.degraded = True
        fallback.degraded_reason = reason
        return self._attach_data_notices(fallback)

    @staticmethod
    def _attach_data_notices(plan: TripPlan) -> TripPlan:
        notices: list[str] = []
        place_items = [item for day in plan.days for item in [*day.attractions, *day.meals] if item.source == "sample"]
        place_items.extend(day.hotel for day in plan.days if day.hotel and day.hotel.source == "sample")
        if place_items:
            notices.append("\u5b9e\u65f6\u5730\u70b9\u6570\u636e\u4e0d\u8db3\uff1a\u5f53\u524d\u5c55\u793a\u7684\u6a21\u62df\u5019\u9009\u4ec5\u4f9b\u6f14\u793a\uff0c\u4e0d\u53ef\u7528\u4e8e\u5bfc\u822a\u6216\u9884\u8ba2\u3002")
        if any(not weather.forecast_available for weather in plan.weather_info):
            notices.append("\u884c\u7a0b\u542b\u6709\u65e0\u6cd5\u786e\u8ba4\u7684\u5929\u6c14\u65e5\u671f\uff0c\u8bf7\u51fa\u884c\u524d\u518d\u6b21\u67e5\u8be2\u3002")
        plan.data_notices = notices
        return plan

    @staticmethod
    def _calculate_budget(days: list[DayPlan], request: TripPlanRequest) -> Budget:
        return calculate_budget(days, request)
