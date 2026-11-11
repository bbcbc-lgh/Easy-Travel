import pytest
from pydantic import ValidationError

from src.model.schemas import TripPlanRequest


def test_end_date_cannot_extend_beyond_the_limit(owned_client, plan_payload, offline_mode) -> None:
    payload = plan_payload(start_date="2026-12-01", end_date="2027-01-09")

    response = owned_client.post("/api/trip/plan", json=payload)

    assert response.status_code == 422


def test_blank_city_is_rejected(owned_client, plan_payload, offline_mode) -> None:
    response = owned_client.post("/api/trip/plan", json=plan_payload(city="   "))

    assert response.status_code == 422


def test_fourteen_days_is_allowed() -> None:
    request = TripPlanRequest(city="北京", start_date="2026-11-20", end_date="2026-12-03")

    assert request.days == 14


def test_fifteen_days_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TripPlanRequest(city="北京", start_date="2026-11-20", end_date="2026-12-04")


def test_city_is_stripped() -> None:
    request = TripPlanRequest(city="  杭州  ", start_date="2026-11-20", days=1)

    assert request.city == "杭州"
