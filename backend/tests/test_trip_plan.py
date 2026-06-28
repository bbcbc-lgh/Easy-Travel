from fastapi.testclient import TestClient

from app.agents.review_agent import ReviewAgent
from app.api.main import app
from app.models.schemas import Attraction, DayPlan, Location, TripPlan, TripPlanRequest
from app.services.amap import AMapService


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
    assert payload["quality"]["score"] > 0
    assert payload["id"]


def test_saved_trip_plan_can_be_loaded_and_listed() -> None:
    create_response = client.post(
        "/api/trip/plan",
        json={
            "city": "杭州",
            "start_date": "2026-07-01",
            "days": 2,
            "preferences": "自然风光和城市漫游",
            "budget": "中等",
            "transportation": "公共交通",
            "accommodation": "经济型酒店",
        },
    )
    assert create_response.status_code == 200
    plan_id = create_response.json()["id"]

    load_response = client.get(f"/api/trip/plans/{plan_id}")
    assert load_response.status_code == 200
    assert load_response.json()["city"] == "杭州"

    list_response = client.get("/api/trip/plans?limit=5")
    assert list_response.status_code == 200
    plan_ids = [item["id"] for item in list_response.json()]
    assert plan_id in plan_ids


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
    assert payload["quality"]["checks"]["no_duplicate_attractions"] is True


def test_review_agent_removes_duplicate_attractions() -> None:
    request = TripPlanRequest(
        city="深圳",
        start_date="2026-07-01",
        days=2,
        preferences="城市漫游",
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )
    attraction = Attraction(
        name="深圳湾公园",
        address="深圳市南山区",
        location=Location(longitude=113.944, latitude=22.517),
        description="滨海公园",
        category="公园",
        ticket_price=0,
    )
    plan = TripPlan(
        city="深圳",
        start_date="2026-07-01",
        end_date="2026-07-02",
        days=[
            DayPlan(
                date="2026-07-01",
                day_index=0,
                description="第一天",
                transportation="公共交通",
                accommodation="经济型酒店",
                attractions=[attraction],
            ),
            DayPlan(
                date="2026-07-02",
                day_index=1,
                description="第二天",
                transportation="公共交通",
                accommodation="经济型酒店",
                attractions=[attraction],
            ),
        ],
        overall_suggestions="测试",
    )

    reviewed = ReviewAgent().run(request, plan, candidate_count=1)
    names = [item.name for day in reviewed.days for item in day.attractions]

    assert names == ["深圳湾公园"]
    assert reviewed.quality is not None
    assert reviewed.quality.checks["no_duplicate_attractions"] is False
    assert reviewed.quality.warnings


def test_amap_attraction_filter_rejects_restaurants() -> None:
    assert AMapService._is_attraction_poi({"type": "风景名胜;公园广场;公园"}) is True
    assert (
        AMapService._is_attraction_poi(
            {"type": "风景名胜;风景名胜相关;旅游景点|餐饮服务;中餐厅;特色餐厅"}
        )
        is False
    )
    assert AMapService._looks_like_non_attraction_name("四季椰林椰子鸡(卓悦中心店)") is True
