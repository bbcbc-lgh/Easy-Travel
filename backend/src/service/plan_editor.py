"""Server-side reconstruction of an edited plan.

A client may only change what a human can reasonably edit: which places, in what
order, and the day descriptions. Every place object is *resolved against the
stored plan* instead of being accepted as submitted, so a client cannot inject a
fabricated venue with its own coordinates, price or provenance.
"""

from datetime import timedelta

from src.model.schemas import Attraction, DayPlan, Hotel, TripPlan, TripPlanRequest
from src.planning.budget import calculate_budget
from src.planning.notices import attach_data_notices


class PlanEditError(Exception):
    """The submitted edit cannot be applied."""


def apply_edits(existing: TripPlan, incoming: TripPlan, request: TripPlanRequest) -> TripPlan:
    if len(incoming.days) != len(existing.days):
        raise PlanEditError(f"day count must stay at {len(existing.days)}")

    attraction_index = {_place_key(item): item for day in existing.days for item in day.attractions}
    hotel_index = {_name_key(day.hotel.name): day.hotel for day in existing.days if day.hotel}
    default_hotel = next((day.hotel for day in existing.days if day.hotel), None)

    days: list[DayPlan] = []
    for index, day in enumerate(incoming.days):
        attractions: list[Attraction] = []
        for item in day.attractions:
            stored = attraction_index.get(_place_key(item))
            if stored is None:
                raise PlanEditError(f"unknown_attraction:{item.name}")
            if any(_place_key(existing_item) == _place_key(stored) for existing_item in attractions):
                continue
            attractions.append(stored)

        hotel: Hotel | None = default_hotel
        if day.hotel is not None:
            resolved_hotel = hotel_index.get(_name_key(day.hotel.name))
            if resolved_hotel is None:
                raise PlanEditError(f"unknown_hotel:{day.hotel.name}")
            hotel = resolved_hotel

        days.append(
            DayPlan(
                date=(request.start_date + timedelta(days=index)).isoformat(),
                day_index=index,
                description=day.description or existing.days[index].description,
                transportation=day.transportation or request.transportation,
                accommodation=day.accommodation or request.accommodation,
                hotel=hotel,
                attractions=attractions,
                routes=[],
            )
        )

    plan = TripPlan(
        id=existing.id,
        city=existing.city,
        start_date=existing.start_date,
        end_date=existing.end_date,
        days=days,
        weather_info=existing.weather_info,
        overall_suggestions=incoming.overall_suggestions or existing.overall_suggestions,
        degraded=existing.degraded,
        degraded_reason=existing.degraded_reason,
    )
    plan.budget = calculate_budget(plan.days, request)
    return attach_data_notices(plan)


def _name_key(name: str) -> str:
    return "".join(name.split()).lower()


def _place_key(item: Attraction) -> tuple[str, str]:
    """Identity of a place: name + address, because AMap repeats names across branches."""
    return (_name_key(item.name), _name_key(item.address))
