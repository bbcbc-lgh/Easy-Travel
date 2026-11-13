"""New request fields travel end to end: must-visit, arrival and departure."""

import pytest

from src.model.schemas import DayPlan, TripPlanRequest
from src.planning.density import HALF_DAY_LOAD, day_load


def test_an_invalid_arrival_time_is_rejected_instead_of_ignored():
    """A malformed time would silently mean "no constraint" if it were accepted."""
    with pytest.raises(ValueError, match="HH:MM"):
        TripPlanRequest(city="杭州", start_date="2026-12-01", days=2, arrival_time="25:99")

    with pytest.raises(ValueError, match="HH:MM"):
        TripPlanRequest(city="杭州", start_date="2026-12-01", days=2, departure_time="noon")


def test_a_blank_time_means_no_constraint():
    request = TripPlanRequest(city="杭州", start_date="2026-12-01", days=2, arrival_time="  ")

    assert request.arrival_time is None


def test_must_visit_names_are_trimmed_deduplicated_and_capped():
    request = TripPlanRequest(
        city="杭州",
        start_date="2026-12-01",
        days=2,
        must_visit=[" 西湖 ", "西湖", "", "灵隐寺"],
    )

    assert request.must_visit == ["西湖", "灵隐寺"]


def test_an_old_stored_request_still_loads():
    """Plans saved before these fields existed must keep deserialising."""
    legacy = (
        '{"city": "杭州", "start_date": "2026-11-20", "days": 2, "preferences": "历史文化",'
        ' "budget": "中等", "transportation": "公共交通", "accommodation": "经济型酒店"}'
    )

    request = TripPlanRequest.model_validate_json(legacy)

    assert request.must_visit == []
    assert request.arrival_time is None
    assert request.departure_time is None


def test_an_arrival_time_shortens_the_first_day_end_to_end(owned_client, offline_mode):
    response = owned_client.post(
        "/api/trip/plan",
        json={
            "city": "杭州",
            "start_date": "2026-11-20",
            "days": 2,
            "preferences": "历史文化",
            "budget": "中等",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
            "arrival_time": "15:00",
        },
    )

    assert response.status_code == 200
    plan = response.json()

    first = DayPlan.model_validate(plan["days"][0])
    assert day_load(first) <= HALF_DAY_LOAD


def test_every_day_gets_a_timeline(owned_client, offline_mode):
    response = owned_client.post(
        "/api/trip/plan",
        json={
            "city": "杭州",
            "start_date": "2026-11-20",
            "days": 2,
            "preferences": "历史文化",
            "budget": "中等",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
        },
    )

    assert response.status_code == 200
    days = response.json()["days"]

    assert all(day["timeline"] for day in days)
    assert days[0]["timeline"][0]["start"] == "09:00"


def test_an_invalid_time_is_a_422_not_a_500(owned_client, offline_mode):
    response = owned_client.post(
        "/api/trip/plan",
        json={
            "city": "杭州",
            "start_date": "2026-11-20",
            "days": 2,
            "arrival_time": "25:99",
        },
    )

    assert response.status_code == 422
