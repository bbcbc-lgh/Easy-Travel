from app.models.schemas import TripPlanRequest, WeatherInfo
from app.services.amap import AMapService


class WeatherQueryAgent:
    def __init__(self, amap_service: AMapService):
        self.amap_service = amap_service

    async def run(self, request: TripPlanRequest) -> list[WeatherInfo]:
        return await self.amap_service.query_weather(request)
