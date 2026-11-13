"""The description phase streams; the route phase does not.

The route is decided by the server after the model answers, so streaming it would
show nothing. The prose is written last and shown to a user who is already looking
at the page, which makes it the one place streaming actually pays.
"""

import asyncio
from types import SimpleNamespace

from src.model.schemas import Attraction, DayPlan, Location, TripPlan, TripPlanRequest
from src.planning.llm_planner import LLMPlanner
from src.service.llm_gateway import LLMGeneration, LLMUnavailableError

HANGZHOU = Location(longitude=120.155, latitude=30.274)


def build_plan() -> TripPlan:
    return TripPlan(
        city="杭州",
        start_date="2026-12-01",
        end_date="2026-12-01",
        days=[
            DayPlan(
                date="2026-12-01",
                day_index=0,
                description="",
                transportation="公共交通",
                accommodation="经济型酒店",
                attractions=[
                    Attraction(
                        name="西湖",
                        address="杭州市",
                        location=HANGZHOU,
                        category="风景名胜;公园广场;公园",
                        source="amap",
                    )
                ],
            )
        ],
        overall_suggestions="慢走",
    )


def build_request() -> TripPlanRequest:
    return TripPlanRequest(city="杭州", start_date="2026-12-01", days=1)


class StreamingGateway:
    settings = SimpleNamespace(plan_two_phase=True)

    def __init__(self, payload: dict, *, fail: bool = False) -> None:
        self.payload = payload
        self.fail = fail
        self.deltas: list[str] = []
        self.stream_calls = 0
        self.plain_calls = 0

    async def generate_json_stream(self, system_prompt, user_prompt, *, on_delta=None, **kwargs):
        self.stream_calls += 1
        if self.fail:
            raise LLMUnavailableError("stream_failed", attempts=1)
        for piece in ("上午沿湖", "散步，", "午后喝茶。"):
            self.deltas.append(piece)
            if on_delta is not None:
                await on_delta(piece)
        return LLMGeneration(
            payload=self.payload,
            value=_validated(self.payload, kwargs.get("validate")),
            profile="fake",
            attempts=1,
            repaired=False,
            elapsed_ms=1.0,
        )

    async def generate_json(self, *args, **kwargs):
        self.plain_calls += 1
        raise AssertionError("the non-streaming path should not run when on_delta is given")


def _validated(payload: dict, validate):
    return validate(payload) if validate is not None else payload


def test_deltas_are_forwarded_as_they_arrive() -> None:
    gateway = StreamingGateway({"days": [{"day_index": 0, "description": "上午沿湖散步，午后喝茶。"}]})
    planner = LLMPlanner(gateway)  # type: ignore[arg-type]
    received: list[str] = []

    async def on_delta(text: str) -> None:
        received.append(text)

    plan = asyncio.run(planner.describe(build_plan(), build_request(), on_delta=on_delta))

    assert received == ["上午沿湖", "散步，", "午后喝茶。"]
    assert gateway.stream_calls == 1
    assert gateway.plain_calls == 0
    assert plan.days[0].description == "上午沿湖散步，午后喝茶。"


def test_a_stream_failure_falls_back_to_a_sentence_not_a_degraded_plan() -> None:
    gateway = StreamingGateway({"days": []}, fail=True)
    planner = LLMPlanner(gateway)  # type: ignore[arg-type]

    async def on_delta(text: str) -> None:
        return None

    plan = asyncio.run(planner.describe(build_plan(), build_request(), on_delta=on_delta))

    assert plan.days[0].attractions[0].name == "西湖"
    assert "西湖" in plan.days[0].description
    assert plan.degraded is False


def test_without_a_callback_the_plain_call_is_used() -> None:
    class PlainGateway:
        settings = SimpleNamespace(plan_two_phase=True)

        def __init__(self) -> None:
            self.calls = 0

        async def generate_json(self, *args, **kwargs):
            self.calls += 1
            payload = {"days": [{"day_index": 0, "description": "上午看湖。"}]}
            validate = kwargs.get("validate")
            return LLMGeneration(
                payload=payload,
                value=validate(payload) if validate else payload,
                profile="fake",
                attempts=1,
                repaired=False,
                elapsed_ms=1.0,
            )

    gateway = PlainGateway()
    plan = asyncio.run(LLMPlanner(gateway).describe(build_plan(), build_request()))  # type: ignore[arg-type]

    assert gateway.calls == 1
    assert plan.days[0].description == "上午看湖。"


def test_prose_that_names_another_days_stop_is_replaced_not_shipped() -> None:
    """The invariant holds at the point of writing, not only at the point of reading."""
    from src.planning.llm_planner import _apply_descriptions

    plan = build_plan()
    second = DayPlan(
        date="2026-12-02",
        day_index=1,
        description="",
        transportation="公共交通",
        accommodation="经济型酒店",
        attractions=[
            Attraction(
                name="灵隐寺",
                address="杭州市",
                location=HANGZHOU,
                category="风景名胜;寺庙道观",
                source="amap",
            )
        ],
    )
    plan.days.append(second)

    _apply_descriptions(plan, {0: "上午去灵隐寺拜佛。", 1: "上午去灵隐寺。"})

    assert "灵隐寺" not in plan.days[0].description, "day 0 must not describe day 1's stop"
    assert plan.days[1].description == "上午去灵隐寺。"
