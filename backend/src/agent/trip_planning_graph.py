import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agent.attraction_agent import AttractionSearchAgent
from src.agent.hotel_agent import HotelAgent
from src.agent.planner_agent import PlannerAgent
from src.agent.review_agent import ReviewAgent
from src.agent.weather_agent import WeatherQueryAgent
from src.model.schemas import Attraction, Hotel, TripPlan, TripPlanRequest, WeatherInfo
from src.planning.critic import PlanCritic, attach_critique
from src.planning.density import parse_clock, trim_days_to_load
from src.planning.timeline import DEFAULT_START_MINUTE, build_timeline, schedule_day
from src.service.amap import AMapService
from src.service.logging import log_event

logger = logging.getLogger(__name__)


class TripPlanningState(TypedDict, total=False):
    """The merged graph state.

    ``total=False`` on purpose: every node returns only the keys it produced, and
    LangGraph merges those into the running state. Reading a key back therefore
    goes through :func:`_require_request` / :func:`_require_plan`, which say what
    the graph wiring should have guaranteed.
    """

    request: TripPlanRequest
    attractions: list[Attraction]
    weather_info: list[WeatherInfo]
    hotels: list[Hotel]
    plan: TripPlan
    candidate_count: int
    feedback: list[str]
    revision: int
    critique: list[str]
    on_event: Callable[..., Awaitable[None]] | None


def _require_request(state: Mapping[str, Any]) -> TripPlanRequest:
    """The trip request this run started with. Missing means a broken invocation."""
    request = state.get("request")
    if not isinstance(request, TripPlanRequest):
        raise RuntimeError("state.request is missing: the graph was not entered with a request")
    return request


def _require_plan(state: Mapping[str, Any]) -> TripPlan:
    """The plan produced by ``create_plan``; every later node depends on it."""
    plan = state.get("plan")
    if not isinstance(plan, TripPlan):
        raise RuntimeError("state.plan is missing: check the graph edges before this node")
    return plan


ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]


class TripPlanningGraph:
    def __init__(
        self,
        attraction_agent: AttractionSearchAgent,
        weather_agent: WeatherQueryAgent,
        hotel_agent: HotelAgent,
        planner_agent: PlannerAgent,
        review_agent: ReviewAgent,
        amap_service: AMapService,
        critic: PlanCritic | None = None,
        max_revisions: int = 0,
    ) -> None:
        self.attraction_agent = attraction_agent
        self.weather_agent = weather_agent
        self.hotel_agent = hotel_agent
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
        builder.add_node("enrich_routes", self._enrich_routes)
        builder.add_node("review_plan", self._review_plan)
        builder.add_node("build_timeline", self._build_timeline)
        builder.add_node("describe_plan", self._describe_plan)

        builder.add_edge(START, "collect_candidates")
        builder.add_edge("collect_candidates", "create_plan")
        builder.add_edge("create_plan", "enrich_routes")
        builder.add_edge("enrich_routes", "review_plan")
        builder.add_conditional_edges(
            "review_plan",
            self._route_after_review,
            {"replan": "create_plan", "done": "build_timeline"},
        )
        builder.add_edge("build_timeline", "describe_plan")
        builder.add_edge("describe_plan", END)
        return builder.compile()

    async def run(self, request: TripPlanRequest, on_event: ProgressCallback | None = None) -> TripPlan:
        started = perf_counter()
        state = await self.graph.ainvoke({"request": request, "revision": 0, "on_event": on_event})
        plan = _require_plan(state)
        # One event for the whole request. `llm.completed` already reports each
        # call, but "how long does a *trip* take" is a different question - and the
        # one the user experiences. Reporting only per-call latency makes a
        # two-phase pipeline look twice as fast as it is.
        log_event(
            logger,
            "planner.finished",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
            city=request.city,
            days=len(plan.days),
            degraded=plan.degraded,
            revisions=state.get("revision", 0),
            attractions=sum(len(day.attractions) for day in plan.days),
        )
        return plan

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
        request = _require_request(state)
        started = perf_counter()
        await self._emit(state, "collect_candidates", "start")
        attractions_task = self.attraction_agent.run(request)
        weather_task = self.weather_agent.run(request)
        hotels_task = self.hotel_agent.run(request)

        attractions, weather_info, hotels = await asyncio.gather(
            attractions_task,
            weather_task,
            hotels_task,
        )
        await self._emit(
            state,
            "collect_candidates",
            "done",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
            attractions=len(attractions),
            hotels=len(hotels),
            weather=len(weather_info),
        )
        return {
            "attractions": attractions,
            "weather_info": weather_info,
            "hotels": hotels,
            "candidate_count": len(attractions),
        }

    async def _create_plan(self, state: TripPlanningState) -> TripPlanningState:
        started = perf_counter()
        await self._emit(state, "create_plan", "start", revision=state.get("revision", 0))
        plan = await self.planner_agent.run(
            _require_request(state),
            state.get("attractions", []),
            state.get("hotels", []),
            state.get("weather_info", []),
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

    async def _enrich_routes(self, state: TripPlanningState) -> TripPlanningState:
        started = perf_counter()
        await self._emit(state, "enrich_routes", "start")
        plan = await self.amap_service.enrich_daily_routes(_require_plan(state), _require_request(state))
        await self._emit(
            state,
            "enrich_routes",
            "done",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
        )
        return {"plan": plan}

    async def _review_plan(self, state: TripPlanningState) -> TripPlanningState:
        request = _require_request(state)
        started = perf_counter()
        await self._emit(state, "review_plan", "start")
        # Critic first, on the plan as the model produced it. It has to see the
        # overload to ask for a replan - trimming before the critique used to make
        # the plan look fine and left the model's own description ("傍晚去万达广场")
        # describing a stop that had already been dropped.
        plan = _require_plan(state)
        critique = self.critic.review(request, plan)
        revision = state.get("revision", 0)
        should_revise = critique.needs_revision and revision < self.max_revisions
        trimmed: list[str] = []

        if not should_revise:
            # Last resort: the model had its chance, so make the day fit by
            # arithmetic. Recalculate the routes of the days that lost a stop,
            # otherwise the route list still points at a place that is gone.
            trimmed, changed_days = trim_days_to_load(plan, request)
            if changed_days:
                plan = await self.amap_service.enrich_daily_routes(plan, request, changed_days)
                critique = self.critic.review(request, plan)

        plan = self.review_agent.run(request, plan, candidate_count=state.get("candidate_count", 0))
        if not should_revise and trimmed:
            if plan.quality is not None:
                plan.quality.warnings.extend(trimmed)
        # Data limitations are only ever warnings; issues go back to the model once,
        # and are shown to the user if there is no retry left.
        attach_critique(plan, critique, will_retry=should_revise)

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

    async def _build_timeline(self, state: TripPlanningState) -> TripPlanningState:
        """Put the day's stops on a clock, inside their opening hours where known.

        Before ``describe_plan`` on purpose: if the order changes to fit opening
        hours, the prose should describe the order that actually ships.
        """
        request = _require_request(state)
        plan = _require_plan(state)
        started = perf_counter()
        await self._emit(state, "build_timeline", "start")

        warnings: list[str] = []
        changed: set[int] = set()
        for day in plan.days:
            before = [item.name for item in day.attractions]
            start_minute = DEFAULT_START_MINUTE
            if day.day_index == 0:
                arrival = parse_clock(request.arrival_time)
                if arrival is not None:
                    start_minute = max(arrival, 0)
            scheduled, day_warnings = schedule_day(day, start_minute)
            warnings.extend(day_warnings)
            if [item.name for item in scheduled.attractions] != before:
                changed.add(day.day_index)

        if changed:
            # The order moved, so the legs between stops are stale.
            try:
                plan = await self.amap_service.enrich_daily_routes(plan, request, changed)
                for day in plan.days:
                    day.timeline = build_timeline(day)
            except Exception as exc:  # noqa: BLE001 - the timetable still works without routes
                log_event(
                    logger,
                    "planner.timeline_route_refresh_failed",
                    level=logging.WARNING,
                    reason=type(exc).__name__,
                    days=sorted(changed),
                )

        if warnings and plan.quality is not None:
            plan.quality.warnings.extend(dict.fromkeys(warnings))

        await self._emit(
            state,
            "build_timeline",
            "done",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
            reordered_days=len(changed),
        )
        return {"plan": plan}

    async def _describe_plan(self, state: TripPlanningState) -> TripPlanningState:
        """Last step: prose for the stops that survived the critic and the trim.

        Deliberately after ``review_plan``: a description written before trimming
        describes a stop the plan no longer contains, which is why the old prompt
        forbade naming places at all.
        """
        started = perf_counter()
        await self._emit(state, "describe_plan", "start")

        async def on_delta(text: str) -> None:
            callback = state.get("on_event")
            if callback is None:
                return
            try:
                await callback({"type": "day_description_delta", "text": text})
            except Exception:  # noqa: BLE001 - reporting must never break planning
                logger.debug("description delta callback failed", exc_info=True)

        plan = await self.planner_agent.describe(
            _require_plan(state),
            _require_request(state),
            on_delta=on_delta if state.get("on_event") is not None else None,
        )
        await self._emit(
            state,
            "describe_plan",
            "done",
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
        )
        return {"plan": plan}
