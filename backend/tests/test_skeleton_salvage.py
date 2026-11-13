"""Every structural mistake the model has actually made, pinned as a test.

A trip used to degrade to the rule planner whenever the model's skeleton broke a
shape rule: an empty day, the wrong number of days, a repeated stop, four stops in
one day. Those were the most common cause of degradation on short trips (2 of 20
in the last live run), and they are all repairable server-side without inventing
anything.

So the failure space is enumerated here, one case per shape seen in a real log.
When a ninth shape shows up it will fail one of these assertions, which is the
point: the class is closed by a fixture, not by the next live run.
"""

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from src.model.schemas import Attraction, Hotel, Location, TripPlanRequest
from src.planning.contracts import CandidatePlaces
from src.planning.llm_planner import DecisionError, LLMPlanner
from src.service.llm_gateway import LLMGeneration

HANGZHOU = Location(longitude=120.155, latitude=30.274)


def attraction(name: str, offset: float = 0.0) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=Location(longitude=120.155 + offset, latitude=30.274 + offset),
        visit_duration=90,
        category="风景名胜;公园广场;公园",
        source="amap",
    )


CANDIDATES = CandidatePlaces(
    attractions=[attraction(f"景点{i}", offset=i * 0.01) for i in range(10)],
    hotels=[
        Hotel(name="甲酒店", address="杭州市", location=HANGZHOU, estimated_cost=280, source="amap"),
        Hotel(name="乙酒店", address="杭州市", location=HANGZHOU, estimated_cost=420, source="amap"),
    ],
    weather=[],
)


def request(days: int = 3) -> TripPlanRequest:
    return TripPlanRequest(city="杭州", start_date=date(2026, 12, 1), days=days)


class ShapeGateway:
    """Returns the payload exactly as the model wrote it, validation included."""

    def __init__(self, payload: dict, *, tool_loop: bool = False) -> None:
        self.payload = payload
        self.settings = SimpleNamespace(plan_two_phase=True, plan_tool_loop=tool_loop)

    async def generate_json(self, system_prompt, user_prompt, *, validate=None, **kwargs):
        value = validate(self.payload) if validate is not None else self.payload
        return LLMGeneration(
            payload=self.payload,
            value=value,
            profile="fake",
            attempts=1,
            repaired=False,
            elapsed_ms=1.0,
        )


def plan_from(payload: dict, *, days: int = 3, tool_loop: bool = False):
    planner = LLMPlanner(ShapeGateway(payload, tool_loop=tool_loop))  # type: ignore[arg-type]
    return asyncio.run(planner.plan(request(days), CANDIDATES))


def assert_well_formed(plan, expected_days: int) -> None:
    assert len(plan.days) == expected_days
    for index, day in enumerate(plan.days):
        assert day.day_index == index
        assert 1 <= len(day.attractions) <= 3, f"day {index} has {len(day.attractions)} stops"
    names = [item.name for day in plan.days for item in day.attractions]
    assert len(names) == len(set(names)), f"repeated stop: {names}"


# --- shape 1: a day with nothing on it ---------------------------------------


def test_an_empty_day_is_filled_instead_of_failing_the_trip() -> None:
    plan = plan_from(
        {
            "days": [
                {"day_index": 0, "attractions": ["景点0"]},
                {"day_index": 1, "attractions": []},
                {"day_index": 2, "attractions": ["景点2"]},
            ]
        }
    )

    assert_well_formed(plan, 3)


# --- shapes 2 and 3: too few / too many days ---------------------------------


def test_too_few_days_are_padded_from_the_pool() -> None:
    plan = plan_from({"days": [{"day_index": 0, "attractions": ["景点0"]}]})

    assert_well_formed(plan, 3)


def test_too_many_days_are_trimmed() -> None:
    plan = plan_from(
        {
            "days": [
                {"day_index": 0, "attractions": ["景点0"]},
                {"day_index": 1, "attractions": ["景点1"]},
                {"day_index": 2, "attractions": ["景点2"]},
                {"day_index": 3, "attractions": ["景点3"]},
                {"day_index": 4, "attractions": ["景点4"]},
            ]
        }
    )

    assert_well_formed(plan, 3)


# --- shape 4: day_index is garbage -------------------------------------------


def test_a_repeated_day_index_falls_back_to_position() -> None:
    plan = plan_from(
        {
            "days": [
                {"day_index": 0, "attractions": ["景点0"]},
                {"day_index": 0, "attractions": ["景点1"]},
                {"day_index": 0, "attractions": ["景点2"]},
            ]
        }
    )

    assert_well_formed(plan, 3)


def test_an_out_of_range_day_index_does_not_lose_the_day() -> None:
    plan = plan_from(
        {
            "days": [
                {"day_index": 9, "attractions": ["景点0"]},
                {"day_index": 1, "attractions": ["景点1"]},
                {"day_index": 2, "attractions": ["景点2"]},
            ]
        }
    )

    assert_well_formed(plan, 3)


# --- shape 5: four stops in one day -----------------------------------------


def test_a_day_is_capped_at_three_stops() -> None:
    plan = plan_from(
        {
            "days": [
                {"day_index": 0, "attractions": ["景点0", "景点1", "景点2", "景点3"]},
                {"day_index": 1, "attractions": ["景点4"]},
                {"day_index": 2, "attractions": ["景点5"]},
            ]
        }
    )

    assert_well_formed(plan, 3)
    assert len(plan.days[0].attractions) == 3


# --- shape 6: the same place on two days ------------------------------------


def test_a_repeated_stop_keeps_its_first_day() -> None:
    plan = plan_from(
        {
            "days": [
                {"day_index": 0, "attractions": ["景点0"]},
                {"day_index": 1, "attractions": ["景点0"]},
                {"day_index": 2, "attractions": ["景点2"]},
            ]
        }
    )

    assert_well_formed(plan, 3)
    assert [item.name for item in plan.days[0].attractions] == ["景点0"]


# --- shape 7: a hotel we never offered --------------------------------------


def test_an_unknown_hotel_falls_back_to_the_default_one() -> None:
    plan = plan_from(
        {
            "days": [
                {"day_index": 0, "attractions": ["景点0"], "hotel": "编造的酒店"},
                {"day_index": 1, "attractions": ["景点1"]},
                {"day_index": 2, "attractions": ["景点2"]},
            ]
        }
    )

    assert_well_formed(plan, 3)
    assert plan.days[0].hotel is not None
    assert plan.days[0].hotel.name == "甲酒店"


# --- shape 8: a place that was never offered --------------------------------


def test_an_unknown_place_still_fails_so_it_can_be_looked_up() -> None:
    """The one shape the server must NOT repair: it is the retrieval retry's job.

    The validator raises; the gateway turns that into ``LLMUnavailableError`` with
    the message in ``detail``, which is what drives the lookup (covered in
    ``test_candidate_lookup.py``).
    """
    payload = {
        "days": [
            {"day_index": 0, "attractions": ["养心殿"]},
            {"day_index": 1, "attractions": ["景点1"]},
            {"day_index": 2, "attractions": ["景点2"]},
        ]
    }

    with pytest.raises(ValueError, match="养心殿.*not in the candidate list"):
        plan_from(payload)


# --- the genuinely unusable case --------------------------------------------


def test_a_skeleton_with_no_usable_place_still_degrades() -> None:
    """Nothing to salvage: the pool gave nothing the model would use."""
    planner = LLMPlanner(ShapeGateway({"days": []}))  # type: ignore[arg-type]

    with pytest.raises(DecisionError):
        asyncio.run(planner.plan(request(3), CandidatePlaces(attractions=[], hotels=[], weather=[])))


# --- and the case that used to pass must keep passing -----------------------


def test_a_well_formed_skeleton_is_untouched() -> None:
    plan = plan_from(
        {
            "days": [
                {"day_index": 0, "attractions": ["景点0", "景点1"], "hotel": "乙酒店"},
                {"day_index": 1, "attractions": ["景点2"]},
                {"day_index": 2, "attractions": ["景点3"]},
            ],
            "overall_suggestions": "慢走",
        }
    )

    assert_well_formed(plan, 3)
    assert plan.days[0].hotel is not None
    assert plan.days[0].hotel.name == "乙酒店"
    assert plan.overall_suggestions == "慢走"
