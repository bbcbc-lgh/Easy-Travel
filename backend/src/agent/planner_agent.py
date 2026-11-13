import logging

from src.model.schemas import Attraction, Hotel, TripPlan, TripPlanRequest, WeatherInfo
from src.planning.contracts import CandidatePlaces
from src.planning.llm_planner import PROMPT_VERSION, DecisionError, LLMPlanner
from src.planning.notices import attach_data_notices
from src.planning.rule_planner import RulePlanner
from src.service.llm_gateway import LLMGateway, LLMUnavailableError
from src.service.logging import log_event

logger = logging.getLogger(__name__)

__all__ = ["PlannerAgent", "PROMPT_VERSION"]


class PlannerAgent:
    """Orchestrates planning: model first, deterministic geometry as fallback."""

    def __init__(self, llm_gateway: LLMGateway, candidate_search=None):
        self.llm_planner = LLMPlanner(llm_gateway, candidate_search=candidate_search)
        self.rule_planner = RulePlanner()

    async def run(
        self,
        request: TripPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
        weather_info: list[WeatherInfo],
        feedback: list[str] | None = None,
    ) -> TripPlan:
        candidates = CandidatePlaces(
            attractions=attractions,
            hotels=hotels,
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
            return attach_data_notices(plan, request)

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
        )
        fallback = await self.rule_planner.plan(request, candidates, feedback)
        fallback.degraded = True
        fallback.degraded_reason = reason
        return attach_data_notices(fallback, request)

    async def describe(self, plan: TripPlan, request: TripPlanRequest, on_delta=None) -> TripPlan:
        """Write the day prose once the route is final.

        Runs after the critic and any trimming, so the descriptions describe the
        itinerary that actually shipped. A failure here is contained: the route is
        already correct, so the fallback is a plain sentence, not a rule-planner
        downgrade.
        """
        described = await self.llm_planner.describe(plan, request, on_delta=on_delta)
        return attach_data_notices(described, request)
