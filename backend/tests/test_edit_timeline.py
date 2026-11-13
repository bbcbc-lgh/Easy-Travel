"""Editing a plan must not lose the timetable it was given.

Found by re-auditing the round that added timelines: `_score_and_critique` re-scored
an edited plan but never rebuilt its timetable, and `apply_edits` builds each day
without one - so the times vanished from the page the moment somebody touched the
plan, and came back stale if the day had been reordered.
"""

from datetime import date
from types import SimpleNamespace

from src.agent.review_agent import ReviewAgent
from src.api.routes import _score_and_critique
from src.model.schemas import Attraction, DayPlan, Location, TripPlan, TripPlanRequest
from src.planning.critic import PlanCritic
from src.planning.timeline import schedule_day

HANGZHOU = Location(longitude=120.155, latitude=30.274)


def request() -> TripPlanRequest:
    return TripPlanRequest(city="杭州", start_date=date(2026, 12, 1), days=1)


def attraction(name: str) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=HANGZHOU,
        visit_duration=90,
        category="风景名胜;公园广场;公园",
        source="amap",
    )


def pipeline() -> SimpleNamespace:
    return SimpleNamespace(review_agent=ReviewAgent(), critic=PlanCritic())


def plan_with_day(names: list[str]) -> TripPlan:
    day = DayPlan(
        date="2026-12-01",
        day_index=0,
        description="编辑过的说明",
        transportation="公共交通",
        accommodation="经济型酒店",
        attractions=[attraction(name) for name in names],
    )
    return TripPlan(
        city="杭州",
        start_date="2026-12-01",
        end_date="2026-12-01",
        days=[day],
        overall_suggestions="测试",
    )


def test_an_edited_plan_regains_its_timetable() -> None:
    plan = plan_with_day(["A", "B"])
    assert plan.days[0].timeline == []

    scored = _score_and_critique(pipeline(), request(), plan)

    assert [slot.name for slot in scored.days[0].timeline] == ["A", "B"]


def test_the_timetable_follows_the_new_order() -> None:
    plan = plan_with_day(["A", "B"])
    schedule_day(plan.days[0])
    plan.days[0].attractions = list(reversed(plan.days[0].attractions))

    scored = _score_and_critique(pipeline(), request(), plan)

    assert [slot.name for slot in scored.days[0].timeline] == ["B", "A"]


def test_a_hotel_leg_is_not_needed_for_a_timetable_to_exist() -> None:
    plan = plan_with_day(["A"])

    scored = _score_and_critique(pipeline(), request(), plan)

    assert scored.days[0].timeline[0].start == "09:00"
