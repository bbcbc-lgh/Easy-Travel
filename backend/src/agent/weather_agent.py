from src.model.schemas import TripPlanRequest, WeatherInfo
from src.service.amap import AMapService


class WeatherQueryAgent:
    def __init__(self, amap_service: AMapService):
        self.amap_service = amap_service

    async def run(self, request: TripPlanRequest) -> list[WeatherInfo]:
        return await self.amap_service.query_weather(request)
