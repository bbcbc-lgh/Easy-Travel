from dataclasses import dataclass
from typing import Protocol

from src.model.schemas import Attraction, Hotel, TripPlan, TripPlanRequest, WeatherInfo


@dataclass(slots=True)
class CandidatePlaces:
    """Everything the pipeline knows about the destination before planning."""

    attractions: list[Attraction]
    hotels: list[Hotel]
    weather: list[WeatherInfo]


class Planner(Protocol):
    """Turns candidates into an itinerary.

    The model-backed implementation decides *what* to visit; the rule-based one
    decides it with geometry. Both share this interface, so they are
    interchangeable and the pipeline never depends on either one.
    """

    async def plan(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None = None,
    ) -> TripPlan: ...
