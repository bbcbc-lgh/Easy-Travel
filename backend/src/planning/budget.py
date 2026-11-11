from src.model.schemas import Budget, DayPlan, TripPlanRequest


def calculate_budget(days: list[DayPlan], request: TripPlanRequest) -> Budget:
    attractions_total = sum(item.ticket_price for day in days for item in day.attractions)
    hotel_nights = max(request.days - 1, 0)
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
