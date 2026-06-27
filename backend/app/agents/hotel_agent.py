from app.models.schemas import Hotel, TripPlanRequest
from app.services.sample_data import sample_hotels


class HotelAgent:
    async def run(self, request: TripPlanRequest) -> list[Hotel]:
        return sample_hotels(request.city, request.accommodation, request.budget)
