from datetime import timedelta

from app.models.schemas import Attraction, Budget, DayPlan, Hotel, Meal, TripPlan, TripPlanRequest, WeatherInfo
from app.services.llm import LLMService
from app.services.sample_data import sample_meals


class PlannerAgent:
    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    async def run(
        self,
        request: TripPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
        weather_info: list[WeatherInfo],
    ) -> TripPlan:
        llm_plan = await self._try_llm_plan(request, attractions, hotels, weather_info)
        if llm_plan is not None:
            return llm_plan
        return self._fallback_plan(request, attractions, hotels, weather_info)

    async def _try_llm_plan(
        self,
        request: TripPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
        weather_info: list[WeatherInfo],
    ) -> TripPlan | None:
        system_prompt = (
            "你是行程规划专家。严格输出 JSON，字段必须符合 TripPlan 模型："
            "city,start_date,end_date,days,weather_info,overall_suggestions,budget。"
            "days 内每项包含 date,day_index,description,transportation,accommodation,hotel,attractions,meals。"
        )
        user_prompt = (
            f"目的地：{request.city}\n"
            f"日期：{request.start_date} 到 {request.end_date}，共 {request.days} 天\n"
            f"偏好：{request.preferences}\n预算：{request.budget}\n"
            f"交通：{request.transportation}\n住宿：{request.accommodation}\n"
            f"候选景点：{[item.model_dump() for item in attractions[:10]]}\n"
            f"候选酒店：{[item.model_dump() for item in hotels[:3]]}\n"
            f"天气：{[item.model_dump() for item in weather_info]}\n"
            "请合理分配每天 2-3 个景点，包含餐饮和预算。"
        )
        payload = await self.llm_service.generate_json(system_prompt, user_prompt)
        if payload is None:
            return None
        try:
            return TripPlan.model_validate(payload)
        except Exception:
            return None

    def _fallback_plan(
        self,
        request: TripPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
        weather_info: list[WeatherInfo],
    ) -> TripPlan:
        selected_hotel = hotels[0] if hotels else None
        meals_template = sample_meals(request.city, request.budget)
        days: list[DayPlan] = []
        for day_index in range(request.days):
            current_date = request.start_date + timedelta(days=day_index)
            day_attractions = attractions[day_index * 2 : day_index * 2 + 3] or attractions[:2]
            meals = [Meal.model_validate(meal.model_dump()) for meal in meals_template]
            days.append(
                DayPlan(
                    date=current_date.isoformat(),
                    day_index=day_index,
                    description=f"第 {day_index + 1} 天围绕 {request.preferences} 安排，节奏适中，预留休息时间。",
                    transportation=request.transportation,
                    accommodation=request.accommodation,
                    hotel=selected_hotel,
                    attractions=day_attractions,
                    meals=meals,
                )
            )

        budget = self._calculate_budget(days, request)
        return TripPlan(
            city=request.city,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            days=days,
            weather_info=weather_info,
            overall_suggestions=(
                f"建议每天优先游览距离较近的景点，使用{request.transportation}衔接。"
                "出发前再次确认景点开放时间、门票预约和天气变化。"
            ),
            budget=budget,
        )

    @staticmethod
    def _calculate_budget(days: list[DayPlan], request: TripPlanRequest) -> Budget:
        attractions_total = sum(item.ticket_price for day in days for item in day.attractions)
        hotel_nights = max(request.days - 1, 1)
        hotel_cost = (days[0].hotel.estimated_cost if days and days[0].hotel else 0) * hotel_nights
        meals_total = sum(meal.estimated_cost for day in days for meal in day.meals)
        transport_unit = {"公共交通": 45, "打车": 120, "自驾": 180}.get(request.transportation, 70)
        transportation_total = transport_unit * request.days
        return Budget(
            total_attractions=attractions_total,
            total_hotels=hotel_cost,
            total_meals=meals_total,
            total_transportation=transportation_total,
        )
