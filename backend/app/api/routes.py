import asyncio

from fastapi import APIRouter, Depends

from app.api.deps import TripPlanningPipeline, get_pipeline
from app.config import settings
from app.models.schemas import HealthResponse, TripPlan, TripPlanRequest

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        services={
            "llm": settings.has_llm,
            "amap": settings.has_amap,
        },
    )


@router.post("/trip/plan", response_model=TripPlan)
async def create_trip_plan(
    request: TripPlanRequest,
    pipeline: TripPlanningPipeline = Depends(get_pipeline),
) -> TripPlan:
    attractions_task = pipeline.attraction_agent.run(request)
    weather_task = pipeline.weather_agent.run(request)
    hotels_task = pipeline.hotel_agent.run(request)

    attractions, weather_info, hotels = await asyncio.gather(
        attractions_task,
        weather_task,
        hotels_task,
    )
    return await pipeline.planner_agent.run(request, attractions, hotels, weather_info)
