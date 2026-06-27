from fastapi.testclient import TestClient

from app.api.main import app


client = TestClient(app)


def test_health_returns_service_flags() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "llm" in payload["services"]


def test_create_trip_plan_with_fallback_data() -> None:
    response = client.post(
        "/api/trip/plan",
        json={
            "city": "北京",
            "start_date": "2026-07-01",
            "days": 3,
            "preferences": "历史文化和城市漫游",
            "budget": "中等",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["city"] == "北京"
    assert len(payload["days"]) == 3
    assert payload["budget"]["total"] > 0
    assert payload["days"][0]["attractions"]


def test_guiyang_fallback_uses_guiyang_coordinates() -> None:
    response = client.post(
        "/api/trip/plan",
        json={
            "city": "贵阳",
            "start_date": "2026-07-01",
            "days": 2,
            "preferences": "自然风光和本地美食",
            "budget": "中等",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    first_attraction = payload["days"][0]["attractions"][0]
    assert first_attraction["location"]["longitude"] < 107
    assert first_attraction["location"]["longitude"] > 106


def test_unknown_city_fallback_does_not_default_to_beijing() -> None:
    response = client.post(
        "/api/trip/plan",
        json={
            "city": "测试城市",
            "start_date": "2026-07-01",
            "days": 1,
            "preferences": "轻松旅行",
            "budget": "中等",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    first_attraction = payload["days"][0]["attractions"][0]
    assert first_attraction["location"]["longitude"] != 116.361128


def test_five_day_plan_does_not_repeat_attractions() -> None:
    response = client.post(
        "/api/trip/plan",
        json={
            "city": "深圳",
            "start_date": "2026-07-01",
            "days": 5,
            "preferences": "城市漫游和本地美食",
            "budget": "中等",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    names = [
        attraction["name"]
        for day in payload["days"]
        for attraction in day["attractions"]
    ]
    assert len(names) == len(set(names))
