from functools import lru_cache

from app.agents.attraction_agent import AttractionSearchAgent
from app.agents.hotel_agent import HotelAgent
from app.agents.planner_agent import PlannerAgent
from app.agents.weather_agent import WeatherQueryAgent
from app.config import settings
from app.services.amap import AMapService
from app.services.llm import LLMService


class TripPlanningPipeline:
    def __init__(self) -> None:
        amap_service = AMapService(settings)
        llm_service = LLMService(settings)
        self.attraction_agent = AttractionSearchAgent(amap_service)
        self.weather_agent = WeatherQueryAgent(amap_service)
        self.hotel_agent = HotelAgent()
        self.planner_agent = PlannerAgent(llm_service)


@lru_cache
def get_pipeline() -> TripPlanningPipeline:
    return TripPlanningPipeline()
