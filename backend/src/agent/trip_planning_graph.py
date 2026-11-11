import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agent.attraction_agent import AttractionSearchAgent
from src.agent.hotel_agent import HotelAgent
from src.agent.meal_agent import MealAgent
from src.agent.planner_agent import PlannerAgent
from src.agent.review_agent import ReviewAgent
from src.agent.weather_agent import WeatherQueryAgent
from src.model.schemas import Attraction, Hotel, Meal, TripPlan, TripPlanRequest, WeatherInfo
from src.planning.budget import calculate_budget
from src.planning.critic import PlanCritic
from src.planning.scheduler import pick_meals
from src.service.amap import AMapService
from src.service.logging import log_event

logger = logging.getLogger(__name__)


class TripPlanningState(TypedDict, total=False):
    request: TripPlanRequest
    attractions: list[Attraction]
    weather_info: list[WeatherInfo]
    hotels: list[Hotel]
    meals: list[Meal]
    plan: TripPlan
    candidate_count: int
    feedback: list[str]
    revision: int
    critique: list[str]
    on_event: Callable[..., Awaitable[None]] | None


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


class TripPlanningGraph:
    def __init__(
        self,
        attraction_agent: AttractionSearchAgent,
        weather_agent: WeatherQueryAgent,
        hotel_agent: HotelAgent,
        meal_agent: MealAgent,
        planner_agent: PlannerAgent,
        review_agent: ReviewAgent,
        amap_service: AMapService,
        critic: PlanCritic | None = None,
        max_revisions: int = 0,
    ) -> None:
        self.attraction_agent = attraction_agent
        self.weather_agent = weather_agent
        self.hotel_agent = hotel_agent
        self.meal_agent = meal_agent
        self.planner_agent = planner_agent
        self.review_agent = review_agent
        self.amap_service = amap_service
        self.critic = critic or PlanCritic()
        self.max_revisions = max(0, max_revisions)
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(TripPlanningState)
        builder.add_node("collect_candidates", self._collect_candidates)
        builder.add_node("create_plan", self._create_plan)
        builder.add_node("enrich_meals", self._enrich_meals)
        builder.add_node("enrich_routes", self._enrich_routes)
        builder.add_node("review_plan", self._review_plan)

        builder.add_edge(START, "collect_candidates")
        builder.add_edge("collect_candidates", "create_plan")
        builder.add_edge("create_plan", "enrich_meals")
        builder.add_edge("enrich_meals", "enrich_routes")
        builder.add_edge("enrich_routes", "review_plan")
        builder.add_conditional_edges(
            "review_plan",
            self._route_after_review,
            {"replan": "create_plan", "done": END},
        )
        return builder.compile()

    async def run(self, request: TripPlanRequest, on_event: ProgressCallback | None = None) -> TripPlan:
        state = await self.graph.ainvoke({"request": request, "revision": 0, "on_event": on_event})
        return state["plan"]

    @staticmethod
    async def _emit(state: TripPlanningState, stage: str, status: str, **fields: Any) -> None:
        callback = state.get("on_event")
        if callback is None:
            return
        try:
            await callback({"type": "stage", "stage": stage, "status": status, **fields})
        except Exception:  # noqa: BLE001 - reporting must never break planning
            logger.debug("progress callback failed", exc_info=True)

    async def _collect_candidates(self, state: TripPlanningState) -> TripPlanningState:
        request = state["request"]
        started = perf_counter()
        await self._emit(state, "collect_candidates", "start")
        attractions_task = self.attraction_agent.run(request)
        weather_task = self.weather_agent.run(request)
        hotels_task = self.hotel_agent.run(request)
        meals_task = self.meal_agent.run(request)

        attractions, weather_info, hotels, meals = await asyncio.gather(
            attractions_task,
            weather_task,
            hotels_task,
            meals_task,
        )
        await self._emit(
            state,
            "collect_candidates",
            "done",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
            attractions=len(attractions),
            hotels=len(hotels),
            meals=len(meals),
            weather=len(weather_info),
        )
        return {
            "attractions": attractions,
            "weather_info": weather_info,
            "hotels": hotels,
            "meals": meals,
            "candidate_count": len(attractions),
        }

    async def _create_plan(self, state: TripPlanningState) -> TripPlanningState:
        started = perf_counter()
        await self._emit(state, "create_plan", "start", revision=state.get("revision", 0))
        plan = await self.planner_agent.run(
            state["request"],
            state.get("attractions", []),
            state.get("hotels", []),
            state.get("weather_info", []),
            state.get("meals", []),
            feedback=state.get("feedback") or None,
        )
        await self._emit(
            state,
            "create_plan",
            "done",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
            degraded=plan.degraded,
        )
        return {"plan": plan}

    async def _enrich_meals(self, state: TripPlanningState) -> TripPlanningState:
        """Re-pick meals using around-search anchored at the hotel and each day's first stop."""
        request = state["request"]
        plan = state["plan"]
        base_pool = list(state.get("meals") or [])
        started = perf_counter()
        await self._emit(state, "enrich_meals", "start")

        picked_days = await self.enrich_meals(request, plan, base_pool)
        await self._emit(
            state,
            "enrich_meals",
            "done",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
            days_with_meals=picked_days,
        )
        return {"plan": plan}

    async def enrich_meals(
        self,
        request: TripPlanRequest,
        plan: TripPlan,
        base_pool: list[Meal],
        day_indexes: set[int] | None = None,
    ) -> int:
        """Re-pick meals around the hotel and each day's first stop.

        Shared by the generation graph and the conversational revision path, so an
        edited day is anchored the same way a freshly generated one is. The
        city-wide ``base_pool`` stays as a fallback: offline/sample runs (no
        coordinates) behave exactly as before.
        """
        targets = [day for day in plan.days if day_indexes is None or day.day_index in day_indexes]
        if not targets:
            return 0

        hotel = next((day.hotel for day in plan.days if day.hotel), None)
        breakfast_pool: list[Meal] = []
        if hotel and hotel.location is not None:
            breakfast_pool = await self.meal_agent.run_around(request, hotel.location, radius=1200, limit=8)

        untouched = [day for day in plan.days if day not in targets]
        used_keys: set[str] = {
            "".join(meal.name.split()).lower() for day in untouched for meal in day.meals
        }
        picked_days = 0
        for day in targets:
            anchor = (
                day.attractions[0].location
                if day.attractions
                else (day.hotel.location if day.hotel else None)
            )
            around: list[Meal] = []
            if anchor is not None:
                around = await self.meal_agent.run_around(request, anchor, radius=2500, limit=10)

            pool = _merge_meals(around, breakfast_pool, base_pool)
            if not pool:
                continue
            preferred = [meal.name for meal in day.meals]
            meals = pick_meals(pool, request, day.hotel, day.attractions, used_keys, preferred=preferred)
            if meals:
                day.meals = meals
                picked_days += 1

        plan.budget = calculate_budget(plan.days, request)
        return picked_days

    async def _enrich_routes(self, state: TripPlanningState) -> TripPlanningState:
        started = perf_counter()
        await self._emit(state, "enrich_routes", "start")
        plan = await self.amap_service.enrich_daily_routes(state["plan"], state["request"])
        await self._emit(
            state,
            "enrich_routes",
            "done",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
        )
        return {"plan": plan}

    async def _review_plan(self, state: TripPlanningState) -> TripPlanningState:
        request = state["request"]
        started = perf_counter()
        await self._emit(state, "review_plan", "start")
        plan = self.review_agent.run(
            request,
            state["plan"],
            candidate_count=state.get("candidate_count", 0),
        )
        critique = self.critic.review(request, plan)
        if plan.quality is not None and critique.notes:
            # Data limitations (e.g. no cheaper restaurant available) are shown
            # to the user, but never trigger another paid model round.
            plan.quality.warnings.extend(critique.notes)
        revision = state.get("revision", 0)
        should_revise = critique.needs_revision and revision < self.max_revisions

        update: TripPlanningState = {"plan": plan, "critique": critique.issues}
        if should_revise:
            log_event(
                logger,
                "planner.revision_requested",
                level=logging.WARNING,
                revision=revision + 1,
                issue_count=len(critique.issues),
                issues=critique.issues,
            )
            update["revision"] = revision + 1
            update["feedback"] = critique.issues
        else:
            if critique.needs_revision:
                log_event(
                    logger,
                    "planner.revision_skipped",
                    level=logging.WARNING,
                    reason="max_revisions_reached" if revision >= self.max_revisions else "no_revision",
                    revision=revision,
                    issue_count=len(critique.issues),
                )
            update["feedback"] = []
        await self._emit(
            state,
            "review_plan",
            "done",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
            score=plan.quality.score if plan.quality else None,
            needs_revision=should_revise,
        )
        return update

    @staticmethod
    def _route_after_review(state: TripPlanningState) -> str:
        return "replan" if state.get("feedback") else "done"


def _merge_meals(*pools: list[Meal]) -> list[Meal]:
    """Deduplicate candidates by name, keeping the first (most local) occurrence."""
    merged: list[Meal] = []
    seen: set[str] = set()
    for pool in pools:
        for meal in pool:
            key = "".join(meal.name.split()).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(meal)
    return merged
