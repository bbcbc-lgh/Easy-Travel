import logging
from datetime import timedelta

from src.model.schemas import DayPlan, TripPlan, TripPlanRequest
from src.planning import must_visit
from src.planning.budget import calculate_budget
from src.planning.contracts import CandidatePlaces
from src.planning.density import attraction_load, capacities_for
from src.planning.scheduler import MAX_ATTRACTIONS_PER_DAY, build_days, enforce_load
from src.service.logging import log_event

logger = logging.getLogger(__name__)


class RulePlanner:
    """Deterministic planner: geometry decides everything.

    It is the fallback when no model is available, and the baseline the model
    path is measured against.
    """

    async def plan(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None = None,
    ) -> TripPlan:
        hotel = candidates.hotels[0] if candidates.hotels else None
        anchor = hotel.location if hotel else None
        # A must-visit place must survive the capacity cut below, so it goes first
        # and the rest of the pool is trimmed to what the days can hold.
        ordered = _must_visit_first(request, candidates.attractions)
        capacity_slots = request.days * MAX_ATTRACTIONS_PER_DAY
        if len(ordered) > capacity_slots:
            pinned = ordered[: len(request.must_visit)]
            ordered = (pinned + ordered[len(pinned) :])[:capacity_slots]
        groups = build_days(ordered, request.days, anchor)
        groups = enforce_load(groups, attraction_load, capacities_for(request.days, request))

        days: list[DayPlan] = []
        for day_index, group in enumerate(groups):
            if group:
                description = f"第 {day_index + 1} 天按距离就近串联 {len(group)} 个点，减少往返，余下时间留给周边慢行。"
            else:
                description = "候选景点不足，今天预留为自由探索和休息。"
            days.append(
                DayPlan(
                    date=(request.start_date + timedelta(days=day_index)).isoformat(),
                    day_index=day_index,
                    description=description,
                    transportation=request.transportation,
                    accommodation=request.accommodation,
                    hotel=hotel,
                    attractions=list(group),
                )
            )

        plan = TripPlan(
            city=request.city,
            start_date=request.start_date.isoformat(),
            end_date=request.resolved_end_date.isoformat(),
            days=days,
            weather_info=list(candidates.weather),
            overall_suggestions=(
                f"建议按区域集中游览，使用{request.transportation}衔接；出发前再次确认开放时间、门票预约和天气变化。"
            ),
            budget=calculate_budget(days, request),
        )
        log_event(
            logger,
            "planner.rules_built",
            city=request.city,
            days=request.days,
            candidate_attractions=len(candidates.attractions),
            feedback_applied=bool(feedback),
        )
        return plan


def _must_visit_first(request: TripPlanRequest, attractions: list) -> list:
    """Put the places the user insists on at the front of the pool."""
    if not request.must_visit:
        return list(attractions)
    pinned = [item for item in attractions if any(must_visit.matches(query, item.name) for query in request.must_visit)]
    rest = [item for item in attractions if item not in pinned]
    return pinned + rest
