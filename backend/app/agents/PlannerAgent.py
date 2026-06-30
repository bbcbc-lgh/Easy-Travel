from datetime import timedelta

from app.models.Schemas import Attraction, Budget, DayPlan, Hotel, Meal, TripPlan, TripPlanRequest, WeatherInfo
from app.services.LLM import LLMService
from app.services.SampleData import sample_meals


class PlannerAgent:
    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    async def run(
        self,
        request: TripPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
        weather_info: list[WeatherInfo],
        meals: list[Meal] | None = None,
    ) -> TripPlan:
        meal_candidates = meals or sample_meals(request.city, request.budget)
        llm_plan = await self._try_llm_plan(request, attractions, hotels, weather_info, meal_candidates)
        if llm_plan is not None:
            return llm_plan
        return self._fallback_plan(request, attractions, hotels, weather_info, meal_candidates)

    async def _try_llm_plan(
        self,
        request: TripPlanRequest,
        attractions: list[Attraction],
        hotels: list[Hotel],
        weather_info: list[WeatherInfo],
        meals: list[Meal],
    ) -> TripPlan | None:
        system_prompt = (
            "你是行程规划专家。严格输出 JSON，字段必须符合 TripPlan 模型："
            "city,start_date,end_date,days,weather_info,overall_suggestions,budget。"
            "days 内每项包含 date,day_index,description,transportation,accommodation,hotel,attractions,meals。"
            "只能使用用户提供的候选景点，不要编造坐标；同一个景点不要重复安排。"
        )
        unique_attractions = self._unique_attractions(attractions)
        user_prompt = (
            f"目的地：{request.city}\n"
            f"日期：{request.start_date} 到 {request.end_date}，共 {request.days} 天\n"
            f"偏好：{request.preferences}\n预算：{request.budget}\n"
            f"交通：{request.transportation}\n住宿：{request.accommodation}\n"
            f"候选景点：{[item.model_dump() for item in unique_attractions[:24]]}\n"
            f"候选酒店：{[item.model_dump() for item in hotels[:3]]}\n"
            f"候选餐饮：{[item.model_dump() for item in meals[:12]]}\n"
            f"天气：{[item.model_dump() for item in weather_info]}\n"
            "请合理分配每天 1-3 个景点，优先使用候选餐饮和候选酒店。候选景点不足时可以减少每日景点数量，不要重复景点。"
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
        meals: list[Meal],
    ) -> TripPlan:
        selected_hotel = hotels[0] if hotels else None
        days: list[DayPlan] = []
        unique_attractions = self._unique_attractions(attractions)
        attraction_cursor = 0
        meal_cursor = 0
        for day_index in range(request.days):
            current_date = request.start_date + timedelta(days=day_index)
            remaining_days = request.days - day_index
            remaining_attractions = len(unique_attractions) - attraction_cursor
            target_count = 0
            if remaining_attractions > 0:
                target_count = max(1, min(3, (remaining_attractions + remaining_days - 1) // remaining_days))
            day_attractions = unique_attractions[attraction_cursor : attraction_cursor + target_count]
            attraction_cursor += target_count
            day_meals = self._pick_day_meals(meals, meal_cursor, request)
            meal_cursor += len(day_meals)
            days.append(
                DayPlan(
                    date=current_date.isoformat(),
                    day_index=day_index,
                    description=f"第 {day_index + 1} 天围绕 {request.preferences} 安排，节奏适中，预留休息时间。",
                    transportation=request.transportation,
                    accommodation=request.accommodation,
                    hotel=selected_hotel,
                    attractions=day_attractions,
                    meals=day_meals,
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
    def _unique_attractions(attractions: list[Attraction]) -> list[Attraction]:
        seen: set[str] = set()
        unique: list[Attraction] = []
        for attraction in attractions:
            key = f"{attraction.name}|{attraction.address}".strip()
            if key in seen:
                continue
            seen.add(key)
            unique.append(attraction)
        return unique

    @staticmethod
    def _pick_day_meals(meals: list[Meal], cursor: int, request: TripPlanRequest) -> list[Meal]:
        if not meals:
            return [Meal.model_validate(meal.model_dump()) for meal in sample_meals(request.city, request.budget)]
        picked = meals[cursor : cursor + 3]
        if len(picked) < 3:
            picked = [*picked, *meals[: 3 - len(picked)]]
        meal_types = ("breakfast", "lunch", "dinner")
        result: list[Meal] = []
        for index, meal in enumerate(picked[:3]):
            payload = meal.model_dump()
            payload["type"] = meal_types[index]
            result.append(Meal.model_validate(payload))
        return result

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
