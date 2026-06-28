from functools import lru_cache

from app.agents.attraction_agent import AttractionSearchAgent
from app.agents.hotel_agent import HotelAgent
from app.agents.meal_agent import MealAgent
from app.agents.planner_agent import PlannerAgent
from app.agents.review_agent import ReviewAgent
from app.agents.weather_agent import WeatherQueryAgent
from app.config import settings
from app.services.amap import AMapService
from app.services.database import TripPlanRepository
from app.services.llm import LLMService


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
