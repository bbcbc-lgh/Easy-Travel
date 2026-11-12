from src.agent.review_agent import ReviewAgent
from src.model.schemas import Attraction, DayPlan, Hotel, Location, TripPlan, TripPlanRequest
from src.service.amap import AMapService
from src.service.sample_data import sample_attractions


def make_request(days: int = 1) -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date="2026-11-20",
        days=days,
        preferences="历史文化",
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def build_plan(*, degraded: bool = False, price_source: str = "api") -> TripPlan:
    attraction_one = Attraction(
        name="景点甲",
        address="杭州市西湖区",
        location=Location(longitude=120.15, latitude=30.27),
        visit_duration=90,
        ticket_price=30,
        price_source=price_source,
        source="amap",
    )
    attraction_two = Attraction(
        name="景点乙",
        address="杭州市上城区",
        location=Location(longitude=120.16, latitude=30.28),
        visit_duration=90,
        ticket_price=30,
        price_source=price_source,
        source="amap",
    )
    hotel = Hotel(
        name="测试酒店",
        address="杭州市上城区",
        estimated_cost=300,
        price_source=price_source,
        source="amap",
    )
    return TripPlan(
        city="杭州",
        start_date="2026-11-20",
        end_date="2026-11-20",
        days=[
            DayPlan(
                date="2026-11-20",
                day_index=0,
                description="测试行程",
                transportation="公共交通",
                accommodation="经济型酒店",
                hotel=hotel,
                attractions=[attraction_one, attraction_two],
            )
        ],
        overall_suggestions="测试",
        degraded=degraded,
        degraded_reason="llm_provider_timeout" if degraded else None,
    )


def test_rule_fallback_plan_cannot_score_one_hundred() -> None:
    plan = ReviewAgent().run(make_request(), build_plan(degraded=True), candidate_count=10)

    assert plan.quality is not None
    assert plan.quality.score <= 60
    assert plan.quality.checks["planned_by_model"] is False
    assert any("规则引擎" in warning for warning in plan.quality.warnings)


def test_model_plan_is_scored_higher_than_fallback() -> None:
    model_plan = ReviewAgent().run(make_request(), build_plan(degraded=False), candidate_count=10)
    fallback_plan = ReviewAgent().run(make_request(), build_plan(degraded=True), candidate_count=10)

    assert model_plan.quality is not None
    assert fallback_plan.quality is not None
    assert model_plan.quality.checks["planned_by_model"] is True
    assert model_plan.quality.score > fallback_plan.quality.score
    assert model_plan.quality.score > 60


def test_unknown_price_source_is_flagged_and_penalised() -> None:
    known = ReviewAgent().run(make_request(), build_plan(price_source="api"), candidate_count=10)
    unknown = ReviewAgent().run(make_request(), build_plan(price_source="unknown"), candidate_count=10)

    assert known.quality is not None
    assert unknown.quality is not None
    assert unknown.quality.checks["prices_are_confirmed"] is False
    assert any("无法确认" in warning for warning in unknown.quality.warnings)
    assert unknown.quality.score < known.quality.score


def test_estimated_price_is_flagged() -> None:
    plan = ReviewAgent().run(make_request(), build_plan(price_source="estimated"), candidate_count=10)

    assert plan.quality is not None
    assert plan.quality.checks["prices_are_confirmed"] is True
    assert any("估算" in warning for warning in plan.quality.warnings)
    assert plan.quality.score <= 95


# --- price provenance at the data layer --------------------------------------


def test_ticket_price_is_not_invented_for_unknown_category() -> None:
    assert AMapService._ticket_price("") == (0, "unknown")
    assert AMapService._ticket_price("景点") == (0, "unknown")
    assert AMapService._ticket_price("购物服务;商场") == (0, "unknown")


def test_ticket_price_is_marked_estimated_for_known_categories() -> None:
    assert AMapService._ticket_price("风景名胜;公园广场;公园") == (30, "estimated")
    assert AMapService._ticket_price("科教文化服务;博物馆;博物馆") == (50, "estimated")


def test_hotel_cost_uses_api_price_when_available() -> None:
    assert AMapService._hotel_cost("中等", "经济型酒店", {"biz_ext": {"cost": "360"}}) == (360, "api")
    assert AMapService._hotel_cost("中等", "经济型酒店", {}) == (280, "estimated")


def test_sample_places_carry_estimated_prices() -> None:
    attractions = sample_attractions("杭州", "历史文化")

    assert attractions
    assert all(item.price_source == "estimated" for item in attractions)
