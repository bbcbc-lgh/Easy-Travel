from fastapi.testclient import TestClient
from unittest.mock import patch
import pytest

from src.agent.review_agent import ReviewAgent
from src.api.deps import get_pipeline
from src.api.main import app
from src.model.llm_profile import ModelProfile
from src.model.schemas import Attraction, DayPlan, Location, TripPlan, TripPlanRequest
from src.service.amap import AMapService
from src.service.llm import LLMClient


CLIENT_ID = "test-client-0001"


class OwnedClient(TestClient):
    """TestClient that always presents an anonymous owner id."""

    def request(self, *args, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("X-Client-Id", CLIENT_ID)
        return super().request(*args, headers=headers, **kwargs)


client = OwnedClient(app)


@pytest.fixture(autouse=True)
def use_sample_data_for_api_tests() -> None:
    get_pipeline.cache_clear()
    with patch("src.api.deps.settings.use_sample_data", True):
        yield
    get_pipeline.cache_clear()


def test_llm_client_uses_profile_timeout_and_no_sdk_retries() -> None:
    profile = ModelProfile(name="deepseek-flash", timeout_seconds=120.0)

    with patch("src.service.llm.AsyncOpenAI") as mock_client:
        LLMClient(profile, api_key="test-key", base_url="https://example.test")

    mock_client.assert_called_once_with(
        api_key="test-key",
        base_url="https://example.test",
        timeout=120.0,
        max_retries=0,
    )


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
    # Sample/offline mode never calls the model, so the plan must say so.
    assert payload["degraded"] is True
    assert payload["degraded_reason"]
    assert payload["quality"]["score"] <= 60
    assert payload["quality"]["checks"]["planned_by_model"] is False
    assert any("规则引擎" in warning for warning in payload["quality"]["warnings"])


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
    loaded = load_response.json()
    assert loaded["city"] == "杭州"
    assert loaded["degraded"] is True
    assert loaded["degraded_reason"]
    assert loaded["quality"]["checks"]["planned_by_model"] is False

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
    assert AMapService._is_attraction_poi({"type": "科教文化服务;学校;职业技术学校"}) is False
    assert AMapService._is_attraction_poi({"type": "科教文化服务;培训机构;培训机构"}) is False


def test_food_preference_is_not_used_to_search_attractions() -> None:
    request = TripPlanRequest(
        city="贵阳",
        start_date="2026-07-01",
        days=4,
        preferences="美食、历史文化",
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )

    keywords = AMapService._build_attraction_keywords(request)

    assert all("美食" not in keyword for keyword in keywords)
    assert "贵阳 历史文化" in keywords
