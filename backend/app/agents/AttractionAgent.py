from app.models.Schemas import Attraction, TripPlanRequest
from app.services.AMap import AMapService


class AttractionSearchAgent:
    def __init__(self, amap_service: AMapService):
        self.amap_service = amap_service

    async def run(self, request: TripPlanRequest) -> list[Attraction]:
        return await self.amap_service.search_attractions(request)
