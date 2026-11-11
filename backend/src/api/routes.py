import asyncio
import contextlib
import json
import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from src.api.deps import TripPlanningPipeline, get_generation_guard, get_pipeline, get_trip_plan_repository
from src.api.security import get_owner_id
from src.config import settings
from src.model.schemas import HealthResponse, PlanPatch, ReviseRequest, ReviseResponse, TripPlan, TripPlanRequest, TripPlanSummary
from src.planning.reviser import PatchError
from src.service.database import TripPlanRepository
from src.service.generation_guard import GenerationGuard, QuotaExceededError, ServerBusyError
from src.service.llm_gateway import LLMUnavailableError
from src.service.logging import log_event
from src.service.plan_editor import PlanEditError, apply_edits

logger = logging.getLogger(__name__)

router = APIRouter()

STREAM_HEARTBEAT_SECONDS = 5.0


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


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
    owner_id: str = Depends(get_owner_id),
    pipeline: TripPlanningPipeline = Depends(get_pipeline),
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
    guard: GenerationGuard = Depends(get_generation_guard),
) -> TripPlan:
    try:
        async with guard.generation_slot(owner_id):
            plan = await pipeline.run(request)
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日生成次数已达上限（{exc.limit} 次），请明天再试",
            headers={"Retry-After": "3600"},
        ) from exc
    except ServerBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="当前生成请求较多，请稍后重试",
            headers={"Retry-After": str(max(int(exc.timeout_seconds), 1))},
        ) from exc
    return repository.save_plan(request, plan, owner_id)


@router.post("/trip/plan/stream")
async def stream_trip_plan(
    http_request: Request,
    request: TripPlanRequest,
    owner_id: str = Depends(get_owner_id),
    pipeline: TripPlanningPipeline = Depends(get_pipeline),
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
    guard: GenerationGuard = Depends(get_generation_guard),
) -> StreamingResponse:
    """Same plan as ``POST /trip/plan``, emitted as Server-Sent Events.

    Events: ``stage`` (start/done per pipeline step), ``heartbeat`` (keeps the
    client honest during long model calls), ``plan`` (final saved plan) and
    ``error``.
    """
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    started = perf_counter()

    async def on_event(event: dict) -> None:
        await queue.put(event)

    async def produce() -> None:
        try:
            async with guard.generation_slot(owner_id):
                plan = await pipeline.run(request, on_event=on_event)
            saved = repository.save_plan(request, plan, owner_id)
            await queue.put(
                {
                    "type": "plan",
                    "plan": saved.model_dump(mode="json"),
                    "elapsed_ms": round((perf_counter() - started) * 1000, 1),
                }
            )
        except QuotaExceededError as exc:
            await queue.put(
                {"type": "error", "code": 429, "detail": f"今日生成次数已达上限（{exc.limit} 次），请明天再试"}
            )
        except ServerBusyError:
            await queue.put({"type": "error", "code": 429, "detail": "当前生成请求较多，请稍后重试"})
        except Exception as exc:  # noqa: BLE001 - the stream must always terminate with an error event
            log_event(
                logger,
                "plan.stream_failed",
                level=logging.ERROR,
                owner_id=owner_id,
                error_type=type(exc).__name__,
                error=str(exc),
                exc_info=True,
            )
            await queue.put({"type": "error", "code": 500, "detail": "生成失败，请稍后重试"})
        finally:
            await queue.put(None)

    async def event_stream():
        task = asyncio.create_task(produce())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=STREAM_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    if await http_request.is_disconnected():
                        log_event(logger, "plan.stream_disconnected", level=logging.INFO, owner_id=owner_id)
                        break
                    yield _sse("heartbeat", {"elapsed_ms": round((perf_counter() - started) * 1000, 1)})
                    continue
                if item is None:
                    break
                yield _sse(item["type"], item)
                if item["type"] in {"plan", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/trip/plans/{plan_id}/revise", response_model=ReviseResponse)
async def revise_trip_plan(
    plan_id: str,
    body: ReviseRequest,
    owner_id: str = Depends(get_owner_id),
    pipeline: TripPlanningPipeline = Depends(get_pipeline),
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
    guard: GenerationGuard = Depends(get_generation_guard),
) -> ReviseResponse:
    """Apply a natural-language edit: the model proposes a patch, the server applies it."""
    plan = repository.get_plan(plan_id, owner_id)
    request = repository.get_request(plan_id, owner_id)
    if plan is None or request is None:
        raise HTTPException(status_code=404, detail="Trip plan not found")

    try:
        async with guard.generation_slot(owner_id):
            candidates = await pipeline.collect_for_edit(request, plan)
            patch = await pipeline.reviser.propose(request, plan, candidates, body.instruction)
            revised = pipeline.reviser.apply(plan, patch, request, candidates)
            changed_days = _days_needing_meal_anchor(patch)
            if changed_days:
                try:
                    await pipeline.enrich_meals(request, revised, candidates, changed_days)
                except Exception as exc:  # noqa: BLE001 - meal enrichment is best effort
                    log_event(
                        logger,
                        "plan.meal_enrichment_failed",
                        level=logging.WARNING,
                        plan_id=plan_id,
                        reason=type(exc).__name__,
                    )
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日生成次数已达上限（{exc.limit} 次），请明天再试",
            headers={"Retry-After": "3600"},
        ) from exc
    except ServerBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="当前请求较多，请稍后重试",
            headers={"Retry-After": str(max(int(exc.timeout_seconds), 1))},
        ) from exc
    except LLMUnavailableError as exc:
        log_event(
            logger,
            "plan.revise_unavailable",
            level=logging.WARNING,
            plan_id=plan_id,
            reason=exc.reason,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="暂时无法理解这条修改要求，请稍后再试",
        ) from exc
    except PatchError as exc:
        raise HTTPException(status_code=422, detail=f"无法应用该修改：{exc}") from exc

    try:
        revised = await pipeline.amap_service.enrich_daily_routes(revised, request)
    except Exception as exc:  # noqa: BLE001 - route enrichment is best effort
        log_event(
            logger,
            "plan.route_enrichment_failed",
            level=logging.WARNING,
            plan_id=plan_id,
            reason=type(exc).__name__,
        )

    revised = _score_and_critique(pipeline, request, revised)
    saved = repository.update_plan(plan_id, revised, owner_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Trip plan not found")
    log_event(
        logger,
        "plan.revised",
        plan_id=plan_id,
        changed_days=len(patch.days),
        instruction_chars=len(body.instruction),
    )
    return ReviseResponse(plan=saved, reply=patch.reply)


@router.get("/trip/plans", response_model=list[TripPlanSummary])
async def list_trip_plans(
    limit: int = 20,
    owner_id: str = Depends(get_owner_id),
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
) -> list[dict]:
    return repository.list_plans(owner_id, limit=limit)


@router.get("/trip/plans/{plan_id}", response_model=TripPlan)
async def get_trip_plan(
    plan_id: str,
    owner_id: str = Depends(get_owner_id),
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
) -> TripPlan:
    plan = repository.get_plan(plan_id, owner_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Trip plan not found")
    return plan


@router.delete("/trip/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip_plan(
    plan_id: str,
    owner_id: str = Depends(get_owner_id),
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
) -> Response:
    if not repository.delete_plan(plan_id, owner_id):
        raise HTTPException(status_code=404, detail="Trip plan not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/trip/plans/{plan_id}", response_model=TripPlan)
async def update_trip_plan(
    plan_id: str,
    plan: TripPlan,
    owner_id: str = Depends(get_owner_id),
    pipeline: TripPlanningPipeline = Depends(get_pipeline),
    repository: TripPlanRepository = Depends(get_trip_plan_repository),
) -> TripPlan:
    existing = repository.get_plan(plan_id, owner_id)
    request = repository.get_request(plan_id, owner_id)
    if existing is None or request is None:
        raise HTTPException(status_code=404, detail="Trip plan not found")

    try:
        sanitized = apply_edits(existing, plan, request)
    except PlanEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        sanitized = await pipeline.amap_service.enrich_daily_routes(sanitized, request)
    except Exception as exc:  # noqa: BLE001 - route enrichment is best effort on save
        log_event(
            logger,
            "plan.route_enrichment_failed",
            level=logging.WARNING,
            plan_id=plan_id,
            reason=type(exc).__name__,
            error=str(exc),
        )

    sanitized = _score_and_critique(pipeline, request, sanitized)
    updated = repository.update_plan(plan_id, sanitized, owner_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Trip plan not found")
    return updated


def _days_needing_meal_anchor(patch: PlanPatch) -> set[int]:
    """Days whose meals depend on changed places and should be re-anchored."""
    return {
        edit.day_index
        for edit in patch.days
        if edit.meals is not None or edit.add_attractions or edit.remove_attractions or edit.hotel
    }


def _score_and_critique(pipeline: TripPlanningPipeline, request: TripPlanRequest, plan: TripPlan) -> TripPlan:
    """Re-score an edited plan and re-attach the critic's notes.

    Generation attaches density/closure/budget notes in the graph; edits and
    revisions go through this path instead, so the same warnings survive a
    manual change.
    """
    plan = pipeline.review_agent.run(request, plan)
    critique = pipeline.critic.review(request, plan)
    if plan.quality is not None and critique.notes:
        plan.quality.warnings.extend(critique.notes)
    return plan
