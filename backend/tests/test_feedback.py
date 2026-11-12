"""Feedback: "this stop is wrong".

The endpoint resolves the reported name against the stored plan, so a row always
points at something the itinerary actually contained - otherwise the summary would
be counting names a client made up.
"""

import pytest

from src.api.deps import get_trip_plan_repository


def create_plan(client, payload) -> dict:
    created = client.post("/api/trip/plan", json=payload())
    assert created.status_code == 200
    return created.json()


def feedback_payload(plan: dict, **overrides) -> dict:
    day = plan["days"][0]
    body = {
        "day_index": 0,
        "target": "attraction",
        "target_name": day["attractions"][0]["name"],
        "reason": "too_packed",
    }
    body.update(overrides)
    return body


def test_feedback_is_recorded(owned_client, plan_payload, offline_mode) -> None:
    plan = create_plan(owned_client, plan_payload)

    response = owned_client.post(f"/api/trip/plans/{plan['id']}/feedback", json=feedback_payload(plan))

    assert response.status_code == 204
    rows = get_trip_plan_repository().feedback_summary()
    assert rows == [{"reason": "too_packed", "target": "attraction", "count": 1}]


def test_a_note_is_kept_verbatim(owned_client, plan_payload, offline_mode) -> None:
    plan = create_plan(owned_client, plan_payload)
    body = feedback_payload(plan, reason="wrong_place", note="这个馆当天在装修")

    owned_client.post(f"/api/trip/plans/{plan['id']}/feedback", json=body)

    notes = get_trip_plan_repository().feedback_notes()
    assert notes[0]["note"] == "这个馆当天在装修"
    assert notes[0]["target_name"] == plan["days"][0]["attractions"][0]["name"]


def test_an_unknown_plan_is_404(owned_client, offline_mode) -> None:
    response = owned_client.post(
        "/api/trip/plans/does-not-exist/feedback",
        json={"day_index": 0, "target": "attraction", "target_name": "x", "reason": "too_far"},
    )

    assert response.status_code == 404


def test_another_owners_plan_is_404(owned_client, other_client, plan_payload, offline_mode) -> None:
    plan = create_plan(owned_client, plan_payload)

    response = other_client.post(f"/api/trip/plans/{plan['id']}/feedback", json=feedback_payload(plan))

    assert response.status_code == 404
    assert get_trip_plan_repository().feedback_summary() == []


def test_a_name_that_is_not_in_the_plan_is_rejected(owned_client, plan_payload, offline_mode) -> None:
    plan = create_plan(owned_client, plan_payload)

    response = owned_client.post(
        f"/api/trip/plans/{plan['id']}/feedback",
        json=feedback_payload(plan, target_name="我编的景点"),
    )

    assert response.status_code == 422
    assert "我编的景点" in response.json()["detail"]


def test_a_day_that_is_not_in_the_plan_is_rejected(owned_client, plan_payload, offline_mode) -> None:
    plan = create_plan(owned_client, plan_payload)

    response = owned_client.post(
        f"/api/trip/plans/{plan['id']}/feedback",
        json=feedback_payload(plan, day_index=9),
    )

    assert response.status_code == 422


def test_an_unknown_reason_is_rejected(owned_client, plan_payload, offline_mode) -> None:
    plan = create_plan(owned_client, plan_payload)

    response = owned_client.post(
        f"/api/trip/plans/{plan['id']}/feedback",
        json=feedback_payload(plan, reason="because-i-said-so"),
    )

    assert response.status_code == 422


def test_meals_can_be_reported(owned_client, plan_payload, offline_mode) -> None:
    plan = create_plan(owned_client, plan_payload)
    meal = plan["days"][0]["meals"][0]

    response = owned_client.post(
        f"/api/trip/plans/{plan['id']}/feedback",
        json=feedback_payload(plan, target="meal", target_name=meal["name"], reason="too_far"),
    )

    assert response.status_code == 204
    assert get_trip_plan_repository().feedback_summary() == [{"reason": "too_far", "target": "meal", "count": 1}]


def test_names_are_compared_ignoring_spacing(owned_client, plan_payload, offline_mode) -> None:
    """The page may render a name with different spacing; that is the same stop."""
    plan = create_plan(owned_client, plan_payload)
    name = plan["days"][0]["attractions"][0]["name"]

    response = owned_client.post(
        f"/api/trip/plans/{plan['id']}/feedback",
        json=feedback_payload(plan, target_name=f" {name} "),
    )

    assert response.status_code == 204


def test_feedback_survives_the_plan_being_deleted(owned_client, plan_payload, offline_mode) -> None:
    """Feedback is a signal about the planner, so it outlives the plan it was about."""
    plan = create_plan(owned_client, plan_payload)
    owned_client.post(f"/api/trip/plans/{plan['id']}/feedback", json=feedback_payload(plan))

    assert owned_client.delete(f"/api/trip/plans/{plan['id']}").status_code == 204

    rows = get_trip_plan_repository().feedback_summary()
    assert rows == [{"reason": "too_packed", "target": "attraction", "count": 1}]


@pytest.mark.parametrize("reason", ["too_packed", "wrong_place", "closed", "too_far", "other"])
def test_every_documented_reason_is_accepted(owned_client, plan_payload, offline_mode, reason) -> None:
    plan = create_plan(owned_client, plan_payload)

    response = owned_client.post(
        f"/api/trip/plans/{plan['id']}/feedback",
        json=feedback_payload(plan, reason=reason),
    )

    assert response.status_code == 204
