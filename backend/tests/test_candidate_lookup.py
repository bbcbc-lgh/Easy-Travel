"""One bounded retrieval retry: go and find the place the model asked for."""

import asyncio
from datetime import date
from types import SimpleNamespace

from src.model.schemas import Attraction, Hotel, Location, TripPlanRequest
from src.planning.contracts import CandidatePlaces
from src.planning.llm_planner import LLMPlanner, _unknown_attraction_names
from src.service.llm_gateway import LLMGeneration, LLMUnavailableError

HANGZHOU = Location(longitude=120.155, latitude=30.274)


def attraction(name: str) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=HANGZHOU,
        category="风景名胜;公园广场;公园",
        source="amap",
    )


def request() -> TripPlanRequest:
    return TripPlanRequest(city="杭州", start_date=date(2026, 12, 1), days=1)


def candidates() -> CandidatePlaces:
    return CandidatePlaces(
        attractions=[attraction("西湖")],
        hotels=[Hotel(name="酒店", address="杭州市", location=HANGZHOU, estimated_cost=280, source="amap")],
        weather=[],
    )


class RetryGateway:
    """Fails the first skeleton with "not in the candidate list", then succeeds."""

    def __init__(self, *, fail_forever: bool = False, tool_loop: bool = True) -> None:
        self.settings = SimpleNamespace(plan_two_phase=True, plan_tool_loop=tool_loop)
        self.fail_forever = fail_forever
        self.calls = 0

    async def generate_json(self, system_prompt, user_prompt, *, validate=None, **kwargs):
        self.calls += 1
        if self.calls == 1 or self.fail_forever:
            raise LLMUnavailableError(
                "schema_invalid",
                attempts=1,
                detail="attraction '养心殿' is not in the candidate list",
            )
        payload = {"days": [{"day_index": 0, "attractions": ["养心殿"], "hotel": "酒店"}]}
        return LLMGeneration(
            payload=payload,
            value=validate(payload) if validate else payload,
            profile="fake",
            attempts=1,
            repaired=False,
            elapsed_ms=1.0,
        )


def test_the_error_message_says_which_place_was_missing() -> None:
    detail = "attraction '养心殿' is not in the candidate list"

    assert _unknown_attraction_names(detail) == ["养心殿"]


def test_an_unrelated_error_yields_no_names() -> None:
    assert _unknown_attraction_names("day 3 must contain at least one attraction") == []


def test_the_planner_looks_the_place_up_and_succeeds_on_the_next_call() -> None:
    looked_up: list[str] = []

    async def search(name: str, req):
        looked_up.append(name)
        return [attraction("养心殿")]

    gateway = RetryGateway()
    planner = LLMPlanner(gateway, candidate_search=search)  # type: ignore[arg-type]

    plan = asyncio.run(planner.plan(request(), candidates()))

    assert looked_up == ["养心殿"]
    assert gateway.calls == 2
    assert plan.days[0].attractions[0].name == "养心殿"


def test_the_loop_runs_once_not_forever() -> None:
    gateway = RetryGateway(fail_forever=True)

    async def search(name: str, req):
        return [attraction("养心殿")]

    planner = LLMPlanner(gateway, candidate_search=search)  # type: ignore[arg-type]

    try:
        asyncio.run(planner.plan(request(), candidates()))
    except LLMUnavailableError:
        pass
    else:  # pragma: no cover - the retry must not succeed silently here
        raise AssertionError("expected the second failure to propagate")

    assert gateway.calls == 2, "exactly one retry"


def test_the_loop_is_skipped_when_disabled() -> None:
    looked_up: list[str] = []

    async def search(name: str, req):  # pragma: no cover - must not run
        looked_up.append(name)
        return [attraction("养心殿")]

    gateway = RetryGateway(tool_loop=False)
    planner = LLMPlanner(gateway, candidate_search=search)  # type: ignore[arg-type]

    try:
        asyncio.run(planner.plan(request(), candidates()))
    except LLMUnavailableError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected the failure to propagate")

    assert looked_up == []
    assert gateway.calls == 1


def test_a_lookup_that_finds_nothing_does_not_retry_the_model() -> None:
    async def search(name: str, req):
        return []

    gateway = RetryGateway()
    planner = LLMPlanner(gateway, candidate_search=search)  # type: ignore[arg-type]

    try:
        asyncio.run(planner.plan(request(), candidates()))
    except LLMUnavailableError as exc:
        assert exc.reason == "candidate_lookup_failed"
    else:  # pragma: no cover
        raise AssertionError("expected a lookup failure")

    assert gateway.calls == 1, "no point asking the model again without new candidates"


def test_the_expanded_candidates_are_not_duplicated() -> None:
    async def search(name: str, req):
        return [attraction("西湖"), attraction("养心殿")]

    gateway = RetryGateway()
    planner = LLMPlanner(gateway, candidate_search=search)  # type: ignore[arg-type]

    plan = asyncio.run(planner.plan(request(), candidates()))

    assert plan.days[0].attractions[0].name == "养心殿"
