from functools import lru_cache

from src.Agent.AttractionAgent import AttractionSearchAgent
from src.Agent.HotelAgent import HotelAgent
from src.Agent.MealAgent import MealAgent
from src.Agent.PlannerAgent import PlannerAgent
from src.Agent.ReviewAgent import ReviewAgent
from src.Agent.TripPlanningGraph import TripPlanningGraph
from src.Agent.WeatherAgent import WeatherQueryAgent
from src.Config import settings
from src.Model.Schemas import TripPlan, TripPlanRequest
from src.Service.AMap import AMapService
from src.Service.Database import TripPlanRepository
from src.Service.LLM import LLMService


class TripPlanningPipeline:
    def __init__(self) -> None:
        amap_service = AMapService(settings)
        llm_service = LLMService(settings)
        self.amap_service = amap_service
        self.attraction_agent = AttractionSearchAgent(amap_service)
        self.weather_agent = WeatherQueryAgent(amap_service)
        self.hotel_agent = HotelAgent(amap_service)
        self.meal_agent = MealAgent(amap_service)
        self.planner_agent = PlannerAgent(llm_service)
        self.review_agent = ReviewAgent()
        self.graph = TripPlanningGraph(
            attraction_agent=self.attraction_agent,
            weather_agent=self.weather_agent,
            hotel_agent=self.hotel_agent,
            meal_agent=self.meal_agent,
            planner_agent=self.planner_agent,
            review_agent=self.review_agent,
            amap_service=self.amap_service,
        )

    async def run(self, request: TripPlanRequest) -> TripPlan:
        return await self.graph.run(request)


@lru_cache
def get_pipeline() -> TripPlanningPipeline:
    return TripPlanningPipeline()


@lru_cache
def get_trip_plan_repository() -> TripPlanRepository:
    return TripPlanRepository(settings)
