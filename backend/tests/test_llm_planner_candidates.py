"""The candidate block is the planner's entire view of the world.

Before this module existed the prompt carried a bare list of names, so the model
could not see distance, price, opening hours or venue type - and then a keyword
critic spent an extra model call repairing the predictable consequences.
"""

import asyncio
from datetime import date
from types import SimpleNamespace

from src.model.schemas import (
    Attraction,
    DayPlan,
    Hotel,
    Location,
    PlanDecision,
    PlanSkeleton,
    TripPlan,
    TripPlanRequest,
    WeatherInfo,
)
from src.planning.candidates import (
    MAX_PROMPT_ATTRACTIONS,
    anchor_location,
    attraction_lines,
    describe_attraction,
    format_closed_days,
    format_distance,
    format_nightly,
    format_price,
    hotel_lines,
    short_category,
)
from src.planning.contracts import CandidatePlaces
from src.planning.llm_planner import LLMPlanner
from src.service.llm_gateway import LLMGeneration, LLMUnavailableError

HANGZHOU = Location(longitude=120.155, latitude=30.274)


def attraction(
    name: str,
    *,
    category: str = "风景名胜;公园广场;公园",
    price: int = 0,
    price_source: str = "estimated",
    hours: str | None = None,
    duration: int = 90,
    location: Location | None = HANGZHOU,
) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=location or HANGZHOU,
        visit_duration=duration,
        category=category,
        ticket_price=price,
        price_source=price_source,  # type: ignore[arg-type]
        opening_hours=hours,
        source="amap",
    )


def hotel(name: str = "测试酒店", *, cost: int = 280, source: str = "estimated") -> Hotel:
    return Hotel(
        name=name,
        address="杭州市",
        location=HANGZHOU,
        estimated_cost=cost,
        price_source=source,  # type: ignore[arg-type]
        type="经济型酒店",
        source="amap",
    )


def test_an_unknown_price_is_never_rendered_as_zero() -> None:
    """0 元 reads as "free", which is a claim the data does not support."""
    text = format_price(0, "unknown")

    assert text == "票价未知"
    assert "免费" not in text
    assert "0" not in text


def test_price_prefixes_carry_provenance() -> None:
    assert format_price(0, "api") == "免费"
    assert format_price(60, "api") == "60元"
    assert format_price(60, "estimated") == "约60元"


def test_nightly_price_has_the_same_provenance_rule() -> None:
    assert format_nightly(hotel(cost=0, source="unknown")) == "房价未知"
    assert format_nightly(hotel(cost=280)) == "约280元/晚"


def test_unknown_opening_hours_say_so_instead_of_looking_open() -> None:
    assert format_closed_days(None) == "开放时间未知"
    assert format_closed_days("") == "开放时间未知"
    assert format_closed_days("周一至周日 09:00-17:00") == "每日开放"
    assert format_closed_days("周二至周日 09:00-16:30，周一闭馆") == "周一闭馆"


def test_closed_days_on_weekends_are_spelled_out() -> None:
    assert format_closed_days("工作日 09:00-17:00，周六周日闭馆") == "周六、周日闭馆"


def test_distance_is_readable_at_both_scales() -> None:
    assert format_distance(0) == "0m"
    assert format_distance(640) == "640m"
    assert format_distance(2100) == "2.1km"
    assert format_distance(float("inf")) == "位置未知"


def test_category_hierarchy_collapses_to_the_specific_segment() -> None:
    assert short_category("风景名胜;公园广场;公园") == "公园"
    assert short_category("科教文化服务;博物馆;博物馆") == "博物馆"
    assert short_category("历史文化") == "历史文化"
    assert short_category("") == "景点"


def test_a_candidate_line_carries_every_fact_the_model_needs() -> None:
    line = describe_attraction(
        attraction("浙江省博物馆", category="科教文化服务;博物馆", price=50, hours="周一闭馆", duration=120),
        HANGZHOU,
    )

    assert line.split(" | ") == [
        "浙江省博物馆",
        "博物馆",
        "约50元",
        "120分钟",
        "周一闭馆",
        "0m",
    ]


def test_a_candidate_without_a_location_does_not_crash_the_prompt() -> None:
    nameless = Attraction(
        name="某景点",
        address="",
        location=HANGZHOU,
        category="公园",
        source="amap",
    )
    line = describe_attraction(nameless, None)

    assert "位置未知" in line


def test_candidate_lists_respect_the_prompt_budget() -> None:
    attractions = [attraction(f"景点{i}") for i in range(40)]

    assert len(attraction_lines(attractions, HANGZHOU)) == MAX_PROMPT_ATTRACTIONS
    assert len(attraction_lines(attractions, HANGZHOU, limit=5)) == 5


def test_a_trimmed_pool_stays_type_diverse() -> None:
    """Cutting the tail would keep 18 museums; round-robin keeps the mix."""
    attractions = [attraction(f"博物馆{i}", category="科教文化服务;博物馆") for i in range(10)]
    attractions += [attraction(f"公园{i}", category="风景名胜;公园广场;公园") for i in range(10)]
    attractions += [attraction(f"老街{i}", category="购物服务;特色街区") for i in range(10)]

    lines = attraction_lines(attractions, HANGZHOU, limit=9)

    assert len(lines) == 9
    assert sum("博物馆" in line for line in lines) == 3
    assert sum("公园" in line for line in lines) == 3
    assert sum("街区" in line for line in lines) == 3


def test_a_pool_that_already_fits_is_returned_in_order() -> None:
    attractions = [attraction("甲"), attraction("乙", category="科教文化服务;博物馆")]

    assert [line.split(" | ")[0] for line in attraction_lines(attractions, HANGZHOU)] == ["甲", "乙"]


def test_hotel_lines_describe_price_and_distance() -> None:
    lines = hotel_lines([hotel()], HANGZHOU)

    assert lines == ["测试酒店 | 经济型酒店 | 约280元/晚 | 0m"]


def test_anchor_sits_where_hydration_will_default_to() -> None:
    """The prompt measures from the first hotel that has a location, like _hydrate."""
    located = hotel("有位置的酒店")
    without_location = Hotel(name="无位置", address="", source="amap")

    assert anchor_location([without_location, located]) is located.location
    assert anchor_location([without_location]) is None


class CapturingGateway:
    """Records the prompt and returns a one-day decision for the first candidate."""

    def __init__(self, payload: dict, *, two_phase: bool = False) -> None:
        self.payload = payload
        self.settings = SimpleNamespace(plan_two_phase=two_phase)
        self.system_prompt = ""
        self.user_prompt = ""
        self.response_schema = None
        self.budget_seconds = None

    async def generate_json(
        self,
        system_prompt,
        user_prompt,
        *,
        prompt_version,
        validate=None,
        response_schema=None,
        budget_seconds=None,
    ):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.response_schema = response_schema
        self.budget_seconds = budget_seconds
        value = validate(self.payload) if validate is not None else self.payload
        return LLMGeneration(
            payload=self.payload,
            value=value,
            profile="fake",
            attempts=1,
            repaired=False,
            elapsed_ms=1.0,
        )


def build_request() -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 12, 1),
        days=1,
        preferences="历史文化",
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def build_candidates() -> CandidatePlaces:
    return CandidatePlaces(
        attractions=[
            attraction("浙江省博物馆", category="科教文化服务;博物馆", price=50, hours="周一闭馆"),
            attraction("西湖", category="风景名胜;公园广场;公园", price_source="unknown"),
        ],
        hotels=[hotel()],
        weather=[
            WeatherInfo(
                date="2026-12-01",
                day_weather="晴",
                night_weather="多云",
                day_temp=18,
                night_temp=9,
                wind_direction="东风",
                wind_power="2级",
            )
        ],
    )


def test_the_prompt_contains_metadata_not_just_names() -> None:
    gateway = CapturingGateway({"days": [{"day_index": 0, "description": "看展", "attractions": ["浙江省博物馆"]}]})
    planner = LLMPlanner(gateway)  # type: ignore[arg-type]

    asyncio.run(planner.plan(build_request(), build_candidates()))

    assert "浙江省博物馆 | 博物馆 | 约50元 | 90分钟 | 周一闭馆" in gateway.user_prompt
    assert "票价未知" in gateway.user_prompt
    assert "| 90分钟 |" in gateway.user_prompt


def test_the_prompt_warns_that_unknown_hours_are_a_risk() -> None:
    gateway = CapturingGateway({"days": [{"day_index": 0, "description": "看展", "attractions": ["西湖"]}]})
    planner = LLMPlanner(gateway)  # type: ignore[arg-type]

    asyncio.run(planner.plan(build_request(), build_candidates()))

    assert "开放时间未知" in gateway.system_prompt
    assert "闭馆" in gateway.system_prompt
    assert "不等于免费" in gateway.system_prompt


def test_the_prompt_still_asks_for_names_only_in_the_output() -> None:
    """The output contract is unchanged: the model picks names, the server hydrates."""
    gateway = CapturingGateway({"days": [{"day_index": 0, "description": "看展", "attractions": ["西湖"]}]})
    planner = LLMPlanner(gateway)  # type: ignore[arg-type]

    plan = asyncio.run(planner.plan(build_request(), build_candidates()))

    assert plan.days[0].attractions[0].name == "西湖"
    assert plan.days[0].attractions[0].location == HANGZHOU
    assert isinstance(PlanDecision.model_validate(gateway.payload), PlanDecision)


def test_the_skeleton_phase_gets_the_same_metadata_and_asks_for_no_prose() -> None:
    gateway = CapturingGateway(
        {"days": [{"day_index": 0, "attractions": ["西湖"], "hotel": "测试酒店"}], "overall_suggestions": "慢走"},
        two_phase=True,
    )
    planner = LLMPlanner(gateway)  # type: ignore[arg-type]

    plan = asyncio.run(planner.plan(build_request(), build_candidates()))

    assert "浙江省博物馆 | 博物馆 | 约50元 | 90分钟 | 周一闭馆" in gateway.user_prompt
    assert "不要输出当日文案" in gateway.system_prompt
    assert gateway.response_schema is PlanSkeleton
    assert plan.days[0].description == "", "prose is written in phase 2"
    assert plan.overall_suggestions == "慢走"


def test_a_long_trip_gets_a_larger_time_budget() -> None:
    """The deadline covers every retry, so a 14-day trip cannot use a 3-day budget."""
    planner = LLMPlanner(CapturingGateway({}, two_phase=True))  # type: ignore[arg-type]

    short = planner._budget_for(build_request())
    long = planner._budget_for(build_request().model_copy(update={"days": 14}))

    assert long > short
    assert long <= 300.0
    assert short >= 150.0


def test_descriptions_only_name_their_own_days_stops() -> None:
    """Phase 2 may name the day's own stops - that is what makes it read like a plan."""
    plan = TripPlan(
        city="杭州",
        start_date="2026-12-01",
        end_date="2026-12-02",
        days=[
            DayPlan(
                date="2026-12-01",
                day_index=0,
                description="",
                transportation="公共交通",
                accommodation="经济型酒店",
                attractions=[attraction("西湖")],
            ),
            DayPlan(
                date="2026-12-02",
                day_index=1,
                description="",
                transportation="公共交通",
                accommodation="经济型酒店",
                attractions=[attraction("灵隐寺")],
            ),
        ],
        overall_suggestions="慢走",
    )
    gateway = CapturingGateway(
        {
            "days": [
                {"day_index": 0, "description": "上午沿西湖走一圈。"},
                {"day_index": 1, "description": "上午去灵隐寺。"},
            ]
        },
        two_phase=True,
    )
    planner = LLMPlanner(gateway)  # type: ignore[arg-type]

    described = asyncio.run(planner.describe(plan, build_request()))

    assert described.days[0].description == "上午沿西湖走一圈。"
    assert described.days[1].description == "上午去灵隐寺。"


def test_a_description_leaking_another_days_stop_is_rejected() -> None:
    plan = TripPlan(
        city="杭州",
        start_date="2026-12-01",
        end_date="2026-12-02",
        days=[
            DayPlan(
                date="2026-12-01",
                day_index=0,
                description="",
                transportation="公共交通",
                accommodation="经济型酒店",
                attractions=[attraction("西湖")],
            ),
            DayPlan(
                date="2026-12-02",
                day_index=1,
                description="",
                transportation="公共交通",
                accommodation="经济型酒店",
                attractions=[attraction("灵隐寺")],
            ),
        ],
        overall_suggestions="慢走",
    )
    gateway = CapturingGateway(
        {
            "days": [
                {"day_index": 0, "description": "上午去灵隐寺。"},
                {"day_index": 1, "description": "上午散步。"},
            ]
        },
        two_phase=True,
    )
    planner = LLMPlanner(gateway)  # type: ignore[arg-type]

    # Not rejected at the validation layer: the leaking day is replaced on write,
    # and the other day keeps its good sentence. Rejecting the whole response paid
    # for a repair round and, when that failed, threw the good prose away too.
    described = asyncio.run(planner.describe(plan, build_request()))

    assert "灵隐寺" not in described.days[0].description
    assert described.days[0].description
    assert described.days[1].description == "上午散步。"


def test_a_failed_description_call_keeps_the_route() -> None:
    """Structure is what the user acts on; a prose failure must not cost the plan."""
    plan = TripPlan(
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
                attractions=[attraction("西湖")],
            )
        ],
        overall_suggestions="慢走",
    )

    class FailingGateway:
        settings = SimpleNamespace(plan_two_phase=True)

        async def generate_json(self, *args, **kwargs):
            raise LLMUnavailableError("provider_timeout", attempts=1)

    described = asyncio.run(LLMPlanner(FailingGateway()).describe(plan, build_request()))  # type: ignore[arg-type]

    assert described.days[0].attractions[0].name == "西湖"
    assert "西湖" in described.days[0].description
