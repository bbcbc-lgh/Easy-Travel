from fastapi.testclient import TestClient

from src.api.main import app

raw_client = TestClient(app)


def test_missing_client_id_is_rejected() -> None:
    response = raw_client.get("/api/trip/plans")

    assert response.status_code == 401
    assert "X-Client-Id" in response.headers.get("www-authenticate", "")


def test_invalid_client_id_is_rejected() -> None:
    response = raw_client.get("/api/trip/plans", headers={"X-Client-Id": "short"})

    assert response.status_code == 401


def test_health_stays_public() -> None:
    assert raw_client.get("/api/health").status_code == 200


def test_plans_are_private_to_their_owner(owned_client, other_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload())
    assert created.status_code == 200
    plan = created.json()

    assert other_client.get(f"/api/trip/plans/{plan['id']}").status_code == 404
    assert other_client.put(f"/api/trip/plans/{plan['id']}", json=plan).status_code == 404
    assert other_client.get("/api/trip/plans").json() == []

    mine = owned_client.get("/api/trip/plans").json()
    assert [item["id"] for item in mine] == [plan["id"]]


def test_list_only_returns_own_plans(owned_client, other_client, plan_payload, offline_mode) -> None:
    first = owned_client.post("/api/trip/plan", json=plan_payload(city="杭州")).json()
    second = other_client.post("/api/trip/plan", json=plan_payload(city="成都")).json()

    mine = owned_client.get("/api/trip/plans").json()
    theirs = other_client.get("/api/trip/plans").json()

    assert [item["id"] for item in mine] == [first["id"]]
    assert [item["id"] for item in theirs] == [second["id"]]

def test_owner_can_delete_their_plan(owned_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()

    response = owned_client.delete(f"/api/trip/plans/{created['id']}")

    assert response.status_code == 204
    assert owned_client.get(f"/api/trip/plans/{created['id']}").status_code == 404
    assert owned_client.get("/api/trip/plans").json() == []


def test_other_owner_cannot_delete_a_plan(owned_client, other_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()

    assert other_client.delete(f"/api/trip/plans/{created['id']}").status_code == 404
    assert owned_client.get(f"/api/trip/plans/{created['id']}").status_code == 200
