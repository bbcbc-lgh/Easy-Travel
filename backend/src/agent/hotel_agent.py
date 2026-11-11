from src.model.schemas import Hotel, TripPlanRequest
from src.service.amap import AMapService


class HotelAgent:
    def __init__(self, amap_service: AMapService):
        self.amap_service = amap_service

    async def run(self, request: TripPlanRequest) -> list[Hotel]:
        return await self.amap_service.search_hotels(request)
