import asyncio
from functools import lru_cache

from src.agent.attraction_agent import AttractionSearchAgent
from src.agent.hotel_agent import HotelAgent
from src.agent.planner_agent import PlannerAgent
from src.agent.review_agent import ReviewAgent
from src.agent.trip_planning_graph import TripPlanningGraph
from src.agent.weather_agent import WeatherQueryAgent
from src.config import Settings, settings
from src.model.schemas import TripPlan, TripPlanRequest
from src.planning.contracts import CandidatePlaces
from src.planning.critic import PlanCritic
from src.planning.reviser import PlanReviser
from src.service.amap import AMapService
from src.service.database import TripPlanRepository
from src.service.generation_guard import GenerationGuard
from src.service.llm_gateway import LLMGateway


class TripPlanningPipeline:
    def __init__(self, config: Settings | None = None) -> None:
        config = config or settings
        amap_service = AMapService(config)
        llm_gateway = LLMGateway(config)
        self.amap_service = amap_service
        self.llm_gateway = llm_gateway
        self.attraction_agent = AttractionSearchAgent(amap_service)
        self.weather_agent = WeatherQueryAgent(amap_service)
        self.hotel_agent = HotelAgent(amap_service)
        self.planner_agent = PlannerAgent(llm_gateway)
        self.reviser = PlanReviser(llm_gateway)
        self.review_agent = ReviewAgent()
        self.critic = PlanCritic()
        self.graph = TripPlanningGraph(
            attraction_agent=self.attraction_agent,
            weather_agent=self.weather_agent,
            hotel_agent=self.hotel_agent,
            planner_agent=self.planner_agent,
            review_agent=self.review_agent,
            amap_service=self.amap_service,
            critic=self.critic,
            max_revisions=config.plan_max_revisions,
        )

    async def run(self, request: TripPlanRequest, on_event=None) -> TripPlan:
        return await self.graph.run(request, on_event=on_event)

    async def collect(self, request: TripPlanRequest) -> CandidatePlaces:
        """Gather candidates for a plan that already exists (conversational edit)."""
        attractions, weather_info, hotels = await asyncio.gather(
            self.attraction_agent.run(request),
            self.weather_agent.run(request),
            self.hotel_agent.run(request),
        )
        return CandidatePlaces(
            attractions=attractions,
            hotels=hotels,
            meals=[],
            weather=weather_info,
        )

    async def collect_for_edit(self, request: TripPlanRequest, plan: TripPlan) -> CandidatePlaces:
        """Candidates for a conversational edit.

        Meals are no longer part of a plan, so this is the same city-wide pool the
        generation path uses.
        """
        return await self.collect(request)


@lru_cache
def get_pipeline() -> TripPlanningPipeline:
    return TripPlanningPipeline()


@lru_cache
def get_trip_plan_repository() -> TripPlanRepository:
    return TripPlanRepository(settings)


@lru_cache
def get_generation_guard() -> GenerationGuard:
    return GenerationGuard(settings)
