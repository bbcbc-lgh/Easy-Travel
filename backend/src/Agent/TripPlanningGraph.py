import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.Agent.AttractionAgent import AttractionSearchAgent
from src.Agent.HotelAgent import HotelAgent
from src.Agent.MealAgent import MealAgent
from src.Agent.PlannerAgent import PlannerAgent
from src.Agent.ReviewAgent import ReviewAgent
from src.Agent.WeatherAgent import WeatherQueryAgent
from src.Model.Schemas import Attraction, Hotel, Meal, TripPlan, TripPlanRequest, WeatherInfo
from src.Service.AMap import AMapService


class TripPlanningState(TypedDict, total=False):
    request: TripPlanRequest
    attractions: list[Attraction]
    weather_info: list[WeatherInfo]
    hotels: list[Hotel]
    meals: list[Meal]
    plan: TripPlan
    candidate_count: int


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
    ) -> None:
        self.attraction_agent = attraction_agent
        self.weather_agent = weather_agent
        self.hotel_agent = hotel_agent
        self.meal_agent = meal_agent
        self.planner_agent = planner_agent
        self.review_agent = review_agent
        self.amap_service = amap_service
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(TripPlanningState)
        builder.add_node("collect_candidates", self._collect_candidates)
        builder.add_node("create_plan", self._create_plan)
        builder.add_node("enrich_routes", self._enrich_routes)
        builder.add_node("review_plan", self._review_plan)

        builder.add_edge(START, "collect_candidates")
        builder.add_edge("collect_candidates", "create_plan")
        builder.add_edge("create_plan", "enrich_routes")
        builder.add_edge("enrich_routes", "review_plan")
        builder.add_edge("review_plan", END)
        return builder.compile()

    async def run(self, request: TripPlanRequest) -> TripPlan:
        state = await self.graph.ainvoke({"request": request})
        return state["plan"]

    async def _collect_candidates(self, state: TripPlanningState) -> TripPlanningState:
        request = state["request"]
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
        return {
            "attractions": attractions,
            "weather_info": weather_info,
            "hotels": hotels,
            "meals": meals,
            "candidate_count": len(attractions),
        }

    async def _create_plan(self, state: TripPlanningState) -> TripPlanningState:
        plan = await self.planner_agent.run(
            state["request"],
            state.get("attractions", []),
            state.get("hotels", []),
            state.get("weather_info", []),
            state.get("meals", []),
        )
        return {"plan": plan}

    async def _enrich_routes(self, state: TripPlanningState) -> TripPlanningState:
        plan = await self.amap_service.enrich_daily_routes(state["plan"], state["request"])
        return {"plan": plan}

    async def _review_plan(self, state: TripPlanningState) -> TripPlanningState:
        plan = self.review_agent.run(
            state["request"],
            state["plan"],
            candidate_count=state.get("candidate_count", 0),
        )
        return {"plan": plan}
