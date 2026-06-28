import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import TripPlanningPipeline, get_pipeline, get_trip_plan_repository
from app.config import settings
from app.models.schemas import HealthResponse, TripPlan, TripPlanRequest, TripPlanSummary
from app.services.database import TripPlanRepository

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        services={
            "llm": settings.has_llm,
            "amap": settings.has_amap,
            "sqlite": True,
        },
    )


@router.post("/trip/plan", response_model=TripPlan)
async def create_trip_plan(
    request: TripPlanRequest,
    pipeline: TripPlanningPipeline = Depends(get_pipeline),
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
) -> TripPlan:
    attractions_task = pipeline.attraction_agent.run(request)
    weather_task = pipeline.weather_agent.run(request)
    hotels_task = pipeline.hotel_agent.run(request)
    meals_task = pipeline.meal_agent.run(request)

    attractions, weather_info, hotels, meals = await asyncio.gather(
        attractions_task,
        weather_task,
        hotels_task,
        meals_task,
    )
    plan = await pipeline.planner_agent.run(request, attractions, hotels, weather_info, meals)
    plan = await pipeline.amap_service.enrich_daily_routes(plan, request)
    reviewed = pipeline.review_agent.run(request, plan, candidate_count=len(attractions))
    return repository.save_plan(request, reviewed)


@router.get("/trip/plans", response_model=list[TripPlanSummary])
async def list_trip_plans(
    limit: int = 20,
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
) -> list[dict]:
    return repository.list_plans(limit=limit)


@router.get("/trip/plans/{plan_id}", response_model=TripPlan)
async def get_trip_plan(
    plan_id: str,
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
) -> TripPlan:
    plan = repository.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Trip plan not found")
    return plan


@router.put("/trip/plans/{plan_id}", response_model=TripPlan)
async def update_trip_plan(
    plan_id: str,
    plan: TripPlan,
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
) -> TripPlan:
    updated = repository.update_plan(plan_id, plan)
    if updated is None:
        raise HTTPException(status_code=404, detail="Trip plan not found")
    return updated
