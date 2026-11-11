import asyncio
from copy import deepcopy

from src.agent.review_agent import ReviewAgent
from src.agent.trip_planning_graph import TripPlanningGraph
from src.model.schemas import Attraction, DayPlan, Hotel, Location, RouteLeg, TripPlan, TripPlanRequest
from src.planning.critic import PlanCritic


def request() -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date="2026-11-20",
        days=1,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


class StubAgent:
    def __init__(self, value) -> None:
        self.value = value

    async def run(self, req):
        return self.value

    async def run_around(self, req, location, radius=2000, limit=10):
        return []


class StubAMap:
    """Assigns a route distance derived from the attraction names."""

    async def enrich_daily_routes(self, plan: TripPlan, req) -> TripPlan:
        for day in plan.days:
            far = any("远" in item.name for item in day.attractions)
            if len(day.attractions) > 1:
                day.routes = [
                    RouteLeg(
                        origin=day.attractions[0].name,
                        destination=day.attractions[1].name,
                        distance_meters=30_000 if far else 1_000,
                        duration_minutes=60,
                        mode=req.transportation,
                    )
                ]
            else:
                day.routes = []
        return plan


class ScriptedPlanner:
    def __init__(self, plans: list[TripPlan]) -> None:
        self.plans = plans
        self.calls = 0
        self.feedbacks: list[list[str] | None] = []

    async def run(self, req, attractions, hotels, weather, meals=None, feedback=None):
        self.feedbacks.append(feedback)
        plan = self.plans[min(self.calls, len(self.plans) - 1)]
        self.calls += 1
        return deepcopy(plan)


def build_plan(prefix: str) -> TripPlan:
    far = prefix == "远"
    hotel = Hotel(name="酒店", address="杭州市", estimated_cost=300, source="amap")
    day = DayPlan(
        date="2026-11-20",
        day_index=0,
        description="测试",
        transportation="公共交通",
        accommodation="经济型酒店",
        hotel=hotel,
        attractions=[
            Attraction(
                name=f"{prefix}景点1",
                address="杭州市",
                location=Location(longitude=120.15, latitude=30.27),
                source="amap",
            ),
            Attraction(
                name=f"{prefix}景点2",
                address="杭州市",
                location=Location(longitude=120.45 if far else 120.151, latitude=30.55 if far else 30.271),
                source="amap",
            ),
        ],
    )
    return TripPlan(
        city="杭州",
        start_date="2026-11-20",
        end_date="2026-11-20",
        days=[day],
        overall_suggestions="测试",
    )


def build_graph(planner: ScriptedPlanner, max_revisions: int) -> TripPlanningGraph:
    return TripPlanningGraph(
        attraction_agent=StubAgent([]),
        weather_agent=StubAgent([]),
        hotel_agent=StubAgent([]),
        meal_agent=StubAgent([]),
        planner_agent=planner,
        review_agent=ReviewAgent(),
        amap_service=StubAMap(),
        critic=PlanCritic(),
        max_revisions=max_revisions,
    )


def test_bad_plan_triggers_one_replan_with_feedback() -> None:
    planner = ScriptedPlanner([build_plan("远"), build_plan("近")])
    graph = build_graph(planner, max_revisions=1)

    plan = asyncio.run(graph.run(request()))

    assert planner.calls == 2
    assert planner.feedbacks[0] is None
    assert planner.feedbacks[1], "the second round must receive the critique"
    assert any("跨度" in issue for issue in planner.feedbacks[1])
    assert all(route.distance_meters == 1_000 for day in plan.days for route in day.routes)


def test_replan_is_capped_by_max_revisions() -> None:
    planner = ScriptedPlanner([build_plan("远")])
    graph = build_graph(planner, max_revisions=0)

    asyncio.run(graph.run(request()))

    assert planner.calls == 1


def test_good_plan_does_not_trigger_replan() -> None:
    planner = ScriptedPlanner([build_plan("近")])
    graph = build_graph(planner, max_revisions=2)

    asyncio.run(graph.run(request()))

    assert planner.calls == 1
