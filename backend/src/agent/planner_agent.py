import logging

from src.model.schemas import Attraction, Hotel, Meal, TripPlan, TripPlanRequest, WeatherInfo
from src.planning.contracts import CandidatePlaces
from src.planning.llm_planner import PROMPT_VERSION, DecisionError, LLMPlanner
from src.planning.notices import attach_data_notices
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
            return attach_data_notices(plan)

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
        return attach_data_notices(fallback)
