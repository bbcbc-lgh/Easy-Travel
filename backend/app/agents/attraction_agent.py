from app.models.schemas import Attraction, TripPlanRequest
from app.services.amap import AMapService
from app.services.unsplash import UnsplashService


class AttractionSearchAgent:
    def __init__(self, amap_service: AMapService, unsplash_service: UnsplashService):
        self.amap_service = amap_service
        self.unsplash_service = unsplash_service

    async def run(self, request: TripPlanRequest) -> list[Attraction]:
        attractions = await self.amap_service.search_attractions(request)
        return await self.unsplash_service.enrich_images(request.city, attractions)
