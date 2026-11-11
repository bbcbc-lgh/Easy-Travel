from copy import deepcopy


def test_client_cannot_forge_quality_budget_or_ownership(owned_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()

    forged = deepcopy(created)
    forged["quality"] = {"score": 100, "warnings": [], "checks": {"planned_by_model": True}}
    forged["budget"]["total"] = 1
    forged["degraded"] = False
    forged["degraded_reason"] = None
    forged["days"][0]["date"] = "1999-01-01"

    response = owned_client.put(f"/api/trip/plans/{created['id']}", json=forged)

    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True, "degraded must come from the stored plan"
    assert body["degraded_reason"] == created["degraded_reason"]
    assert body["quality"]["score"] < 100
    assert body["quality"]["checks"]["planned_by_model"] is False
    assert body["budget"]["total"] != 1
    assert body["days"][0]["date"] != "1999-01-01"
    assert body["budget"]["total"] == sum(
        body["budget"][key] for key in ("total_attractions", "total_hotels", "total_meals", "total_transportation")
    )


def test_day_count_cannot_change_via_edit(owned_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload(days=3)).json()

    shortened = deepcopy(created)
    shortened["days"] = shortened["days"][:2]

    response = owned_client.put(f"/api/trip/plans/{created['id']}", json=shortened)

    assert response.status_code == 422


def test_editing_recomputes_routes_and_preserves_weather(owned_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()

    edited = deepcopy(created)
    edited["weather_info"] = []
    edited["days"][0]["attractions"] = edited["days"][0]["attractions"][:1]
    edited["days"][0]["routes"] = [
        {
            "origin": "伪造起点",
            "destination": "伪造终点",
            "distance_meters": 1,
            "duration_minutes": 1,
            "mode": "fake",
        }
    ]

    response = owned_client.put(f"/api/trip/plans/{created['id']}", json=edited)

    assert response.status_code == 200
    body = response.json()
    assert body["weather_info"] == created["weather_info"]
    assert all(route["origin"] != "伪造起点" for route in body["days"][0]["routes"])


def test_edit_unknown_plan_returns_404(owned_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()

    response = owned_client.put("/api/trip/plans/does-not-exist", json=created)

    assert response.status_code == 404


# --- place objects are resolved server-side (defect: PUT trusted the client) ---


def test_put_rejects_an_unknown_attraction(owned_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()

    forged = deepcopy(created)
    forged["days"][0]["attractions"][0] = {
        "name": "伪造景点",
        "address": "火星",
        "location": {"longitude": 0, "latitude": 0},
        "visit_duration": 60,
        "description": "伪造",
        "category": "景点",
        "ticket_price": 999,
        "price_source": "api",
        "source": "amap",
    }

    response = owned_client.put(f"/api/trip/plans/{created['id']}", json=forged)

    assert response.status_code == 422
    assert "unknown_attraction" in response.json()["detail"]


def test_put_rejects_an_unknown_meal(owned_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()

    forged = deepcopy(created)
    forged["days"][0]["meals"][0]["name"] = "伪造餐厅"

    response = owned_client.put(f"/api/trip/plans/{created['id']}", json=forged)

    assert response.status_code == 422
    assert "unknown_meal" in response.json()["detail"]


def test_put_ignores_client_supplied_prices(owned_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()
    original = created["days"][0]["attractions"][0]

    forged = deepcopy(created)
    forged["days"][0]["attractions"][0]["ticket_price"] = 9999
    forged["days"][0]["attractions"][0]["price_source"] = "api"

    response = owned_client.put(f"/api/trip/plans/{created['id']}", json=forged)

    assert response.status_code == 200
    body = response.json()
    stored = body["days"][0]["attractions"][0]
    assert stored["ticket_price"] == original["ticket_price"]
    assert body["budget"]["total_attractions"] == created["budget"]["total_attractions"]


# --- critic notes survive an edit or a revision (defect: notes were lost) -----


def test_edit_re_attaches_critic_notes(owned_client, plan_payload, offline_mode, monkeypatch) -> None:
    from src.api.deps import get_pipeline
    from src.planning.critic import Critique

    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()
    pipeline = get_pipeline()
    monkeypatch.setattr(
        pipeline.critic,
        "review",
        lambda request, plan: Critique(notes=["第 1 天安排较满，建议减一个景点。"]),
    )

    edited = deepcopy(created)
    edited["days"][0]["description"] = "手动调整后的第一天"

    response = owned_client.put(f"/api/trip/plans/{created['id']}", json=edited)

    assert response.status_code == 200
    assert any("安排较满" in warning for warning in response.json()["quality"]["warnings"])


def test_revision_re_attaches_critic_notes(owned_client, plan_payload, offline_mode, monkeypatch) -> None:
    from src.api.deps import get_pipeline
    from src.model.schemas import DayEdit, PlanPatch
    from src.planning.critic import Critique

    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()
    pipeline = get_pipeline()

    async def fake_propose(request, plan, candidates, instruction):
        return PlanPatch(days=[DayEdit(day_index=0, description="改成室内")], reply="已调整")

    monkeypatch.setattr(pipeline.reviser, "propose", fake_propose)
    monkeypatch.setattr(
        pipeline.critic,
        "review",
        lambda request, plan: Critique(notes=["第 1 天可能闭馆，请确认。"]),
    )

    response = owned_client.post(
        f"/api/trip/plans/{created['id']}/revise",
        json={"instruction": "第 1 天换成室内"},
    )

    assert response.status_code == 200
    assert any("可能闭馆" in warning for warning in response.json()["plan"]["quality"]["warnings"])
