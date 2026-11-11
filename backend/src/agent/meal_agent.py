from src.model.schemas import Location, Meal, TripPlanRequest
from src.service.amap import AMapService


class MealAgent:
    def __init__(self, amap_service: AMapService):
        self.amap_service = amap_service

    async def run(self, request: TripPlanRequest) -> list[Meal]:
        return await self.amap_service.search_meals(request)

    async def run_around(
        self,
        request: TripPlanRequest,
        location: Location,
        radius: int = 2000,
        limit: int = 10,
    ) -> list[Meal]:
        return await self.amap_service.search_meals_around(
            request,
            location,
            radius=radius,
            limit=limit,
        )
