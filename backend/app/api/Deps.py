from functools import lru_cache

from app.agents.AttractionAgent import AttractionSearchAgent
from app.agents.HotelAgent import HotelAgent
from app.agents.MealAgent import MealAgent
from app.agents.PlannerAgent import PlannerAgent
from app.agents.ReviewAgent import ReviewAgent
from app.agents.WeatherAgent import WeatherQueryAgent
from app.Config import settings
from app.services.AMap import AMapService
from app.services.Database import TripPlanRepository
from app.services.LLM import LLMService


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


@lru_cache
def get_pipeline() -> TripPlanningPipeline:
    return TripPlanningPipeline()


@lru_cache
def get_trip_plan_repository() -> TripPlanRepository:
    return TripPlanRepository(settings)
