from app.models.Schemas import Meal, TripPlanRequest
from app.services.AMap import AMapService


class MealAgent:
    def __init__(self, amap_service: AMapService):
        self.amap_service = amap_service

    async def run(self, request: TripPlanRequest) -> list[Meal]:
        return await self.amap_service.search_meals(request)
