import asyncio
from functools import lru_cache

from src.agent.attraction_agent import AttractionSearchAgent
from src.agent.hotel_agent import HotelAgent
from src.agent.meal_agent import MealAgent
from src.agent.planner_agent import PlannerAgent
from src.agent.review_agent import ReviewAgent
from src.agent.trip_planning_graph import TripPlanningGraph
from src.agent.weather_agent import WeatherQueryAgent
from src.config import Settings, settings
from src.model.schemas import Meal, TripPlan, TripPlanRequest
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
        self.meal_agent = MealAgent(amap_service)
        self.planner_agent = PlannerAgent(llm_gateway)
        self.reviser = PlanReviser(llm_gateway)
        self.review_agent = ReviewAgent()
        self.critic = PlanCritic()
        self.graph = TripPlanningGraph(
            attraction_agent=self.attraction_agent,
            weather_agent=self.weather_agent,
            hotel_agent=self.hotel_agent,
            meal_agent=self.meal_agent,
            planner_agent=self.planner_agent,
            review_agent=self.review_agent,
            amap_service=self.amap_service,
            critic=self.critic,
            max_revisions=config.plan_max_revisions,
        )

    async def run(self, request: TripPlanRequest, on_event=None) -> TripPlan:
        return await self.graph.run(request, on_event=on_event)

    async def enrich_meals(
        self,
        request: TripPlanRequest,
        plan: TripPlan,
        candidates: CandidatePlaces,
        day_indexes: set[int] | None = None,
    ) -> int:
        """Re-anchor meals around the hotel/first stop, as generation does."""
        return await self.graph.enrich_meals(request, plan, list(candidates.meals), day_indexes)

    async def collect(self, request: TripPlanRequest) -> CandidatePlaces:
        """Gather candidates for a plan that already exists (conversational edit)."""
        attractions, weather_info, hotels, meals = await asyncio.gather(
            self.attraction_agent.run(request),
            self.weather_agent.run(request),
            self.hotel_agent.run(request),
            self.meal_agent.run(request),
        )
        return CandidatePlaces(
            attractions=attractions,
            hotels=hotels,
            meals=meals,
            weather=weather_info,
        )

    async def collect_for_edit(self, request: TripPlanRequest, plan: TripPlan) -> CandidatePlaces:
        """Candidates for a conversational edit, with meals anchored to the plan.

        The city-wide search can surface restaurants a dozen kilometres away, and the
        reviser can only choose what it is given. Around-search on each day's hotel
        and first stop keeps every meal candidate walkable from somewhere in the plan.
        Falls back to the city pool when around-search yields nothing (offline runs).
        """
        base = await self.collect(request)
        local: list[Meal] = []
        seen: set[str] = set()
        for day in plan.days:
            anchors = [item.location for item in day.attractions[:1]]
            if day.hotel and day.hotel.location:
                anchors.append(day.hotel.location)
            for anchor in anchors:
                for meal in await self.meal_agent.run_around(request, anchor, radius=2500, limit=10):
                    key = "".join(meal.name.split()).lower()
                    if key and key not in seen:
                        seen.add(key)
                        local.append(meal)

        if not local:
            return base
        return CandidatePlaces(
            attractions=base.attractions,
            hotels=base.hotels,
            meals=local,
            weather=base.weather,
        )


@lru_cache
def get_pipeline() -> TripPlanningPipeline:
    return TripPlanningPipeline()


@lru_cache
def get_trip_plan_repository() -> TripPlanRepository:
    return TripPlanRepository(settings)


@lru_cache
def get_generation_guard() -> GenerationGuard:
    return GenerationGuard(settings)
