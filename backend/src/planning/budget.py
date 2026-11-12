from src.model.schemas import Budget, DayPlan, TripPlanRequest

#: Rough in-city travel allowance per day, by the mode the user picked.
TRANSPORT_DAILY = {"公共交通": 45, "打车": 120, "自驾": 180}
DEFAULT_TRANSPORT_DAILY = 70

#: Meal allowance per person per day, by budget tier. Meals are no longer planned,
#: so this is an allowance rather than a sum over chosen restaurants - the traveller
#: decides where to eat and this keeps the estimate honest instead of zero.
MEAL_ALLOWANCE_DAILY = {"经济": 60, "中等": 100, "舒适": 160, "豪华": 260}
DEFAULT_MEAL_ALLOWANCE = 100
PLANNED_TRAVELLERS = 1


def calculate_budget(days: list[DayPlan], request: TripPlanRequest) -> Budget:
    """Sum what the plan actually implies.

    Lodging is charged per *night actually spent*: every day except the last one
    is a night, priced at that day's own hotel. Reading the price off day 1 only
    (the old behaviour) silently under-reported any plan whose hotel changes
    mid-trip, which the reviser can produce.

    A night whose hotel is missing falls back to the first priced hotel in the
    plan rather than counting as free — an unknown price is not a zero price.
    """
    attractions_total = sum(item.ticket_price for day in days for item in day.attractions)
    priced_hotels = [day.hotel for day in days if day.hotel and day.hotel.estimated_cost]
    fallback_hotel = priced_hotels[0] if priced_hotels else None
    hotel_cost = 0
    for night in days[:-1]:
        hotel = night.hotel or fallback_hotel
        if hotel is not None:
            hotel_cost += hotel.estimated_cost
    allowance = MEAL_ALLOWANCE_DAILY.get(request.budget, DEFAULT_MEAL_ALLOWANCE)
    meals_total = allowance * request.days * PLANNED_TRAVELLERS
    transport_unit = TRANSPORT_DAILY.get(request.transportation, DEFAULT_TRANSPORT_DAILY)
    transportation_total = transport_unit * request.days
    return Budget(
        total_attractions=attractions_total,
        total_hotels=hotel_cost,
        total_meals=meals_total,
        total_transportation=transportation_total,
    )
