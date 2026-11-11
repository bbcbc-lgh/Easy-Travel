from datetime import date

import pytest

from src.api.deps import get_pipeline
from src.model.schemas import (
    Attraction,
    DayEdit,
    DayPlan,
    Hotel,
    Location,
    Meal,
    PlanPatch,
    TripPlan,
    TripPlanRequest,
)
from src.planning.contracts import CandidatePlaces
from src.planning.reviser import PatchError, PlanReviser
from src.service.llm_gateway import LLMUnavailableError


def request() -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 11, 20),
        days=2,
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences="历史文化",
    )


def attraction(name: str, longitude: float, price: int = 30) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=Location(longitude=longitude, latitude=30.27),
        category="博物馆",
        ticket_price=price,
        price_source="api",
        source="amap",
    )


def hotel(name: str = "测试酒店") -> Hotel:
    return Hotel(
        name=name,
        address="杭州市",
        location=Location(longitude=120.15, latitude=30.27),
        estimated_cost=300,
        price_source="api",
        source="amap",
    )


def meal(name: str, cost: int = 40, meal_type: str = "lunch") -> Meal:
    return Meal(
        type=meal_type,
        name=name,
        address="杭州市",
        location=Location(longitude=120.15, latitude=30.27),
        estimated_cost=cost,
        price_source="api",
        source="amap",
    )


def build_plan() -> TripPlan:
    days = []
    for index in range(2):
        days.append(
            DayPlan(
                date=f"2026-11-2{index}",
                day_index=index,
                description=f"第 {index + 1} 天",
                transportation="公共交通",
                accommodation="经济型酒店",
                hotel=hotel(),
                attractions=[
                    attraction(f"博物馆{index}A", 120.15 + index * 0.01),
                    attraction(f"博物馆{index}B", 120.15 + index * 0.01 + 0.002),
                ],
                meals=[meal("面馆", 40), meal("小炒", 60), meal("早餐铺", 20)],
            )
        )
    plan = TripPlan(
        city="杭州",
        start_date="2026-11-20",
        end_date="2026-11-21",
        days=days,
        overall_suggestions="原建议",
        degraded=False,
    )
    return plan


def candidates() -> CandidatePlaces:
    return CandidatePlaces(
        attractions=[
            attraction("博物馆0A", 120.15),
            attraction("博物馆1A", 120.16),
            attraction("美术馆新", 120.17, price=50),
        ],
        hotels=[hotel("测试酒店"), hotel("新酒店")],
        meals=[meal("面馆", 40), meal("小炒", 60), meal("早餐铺", 20), meal("新餐厅", 45)],
        weather=[],
    )


class FakeGateway:
    async def generate_json(self, *args, **kwargs):
        raise AssertionError("not used in these tests")


def apply(patch: PlanPatch, plan: TripPlan | None = None) -> TripPlan:
    return PlanReviser(FakeGateway()).apply(plan or build_plan(), patch, request(), candidates())


def test_patch_can_add_a_place_and_recompute_budget() -> None:
    plan = build_plan()
    before_total = sum(item.ticket_price for day in plan.days for item in day.attractions)

    revised = apply(
        PlanPatch(days=[DayEdit(day_index=0, add_attractions=["美术馆新"])], reply="加了美术馆"),
        plan,
    )

    names = [item.name for item in revised.days[0].attractions]
    assert "美术馆新" in names
    assert revised.budget is not None
    assert revised.budget.total_attractions == before_total + 50


def test_patch_can_remove_a_place() -> None:
    revised = apply(
        PlanPatch(days=[DayEdit(day_index=0, remove_attractions=["博物馆0A"])], reply="删掉博物馆"),
    )

    names = [item.name for item in revised.days[0].attractions]
    assert "博物馆0A" not in names
    assert "博物馆0B" in names


def test_removing_every_attraction_is_rejected() -> None:
    with pytest.raises(PatchError):
        apply(
            PlanPatch(
                days=[DayEdit(day_index=0, remove_attractions=["博物馆0A", "博物馆0B"])],
                reply="全删",
            )
        )


def test_patch_updates_description_and_overall_suggestions() -> None:
    revised = apply(
        PlanPatch(
            days=[DayEdit(day_index=1, description="第 2 天改为室内展览")],
            overall_suggestions="新的整体建议",
            reply="调整为室内",
        )
    )

    assert revised.days[1].description == "第 2 天改为室内展览"
    assert revised.days[0].description == "第 1 天"
    assert revised.overall_suggestions == "新的整体建议"


def test_patch_can_replace_meals_from_candidates() -> None:
    revised = apply(
        PlanPatch(days=[DayEdit(day_index=0, meals=["新餐厅"])], reply="换了餐厅"),
    )

    names = [item.name for item in revised.days[0].meals]
    assert "新餐厅" in names


def test_unknown_attraction_in_patch_is_rejected() -> None:
    with pytest.raises(PatchError):
        apply(PlanPatch(days=[DayEdit(day_index=0, add_attractions=["不存在的地方"])], reply="加"))


def test_unknown_hotel_in_patch_is_rejected() -> None:
    with pytest.raises(PatchError):
        apply(PlanPatch(days=[DayEdit(day_index=0, hotel="不存在的酒店")], reply="换酒店"))


# --- API level ---------------------------------------------------------------


def test_revise_requires_ownership(owned_client, other_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()

    response = other_client.post(
        f"/api/trip/plans/{created['id']}/revise",
        json={"instruction": "第 1 天换室内的"},
    )

    assert response.status_code == 404


def test_revise_rejects_blank_instruction(owned_client, plan_payload, offline_mode) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()

    response = owned_client.post(f"/api/trip/plans/{created['id']}/revise", json={"instruction": "   "})

    assert response.status_code == 422


def test_revise_applies_patch_and_persists(owned_client, plan_payload, offline_mode, monkeypatch) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload(days=3)).json()
    pipeline = get_pipeline()

    async def fake_propose(request, plan, candidates, instruction):
        return PlanPatch(
            days=[DayEdit(day_index=0, description="第 1 天改为室内展览")],
            reply="已把第 1 天改成室内安排",
        )

    monkeypatch.setattr(pipeline.reviser, "propose", fake_propose)

    response = owned_client.post(
        f"/api/trip/plans/{created['id']}/revise",
        json={"instruction": "第 1 天换成室内的"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "已把第 1 天改成室内安排"
    assert body["plan"]["days"][0]["description"] == "第 1 天改为室内展览"
    assert body["plan"]["budget"]["total"] > 0

    reloaded = owned_client.get(f"/api/trip/plans/{created['id']}").json()
    assert reloaded["days"][0]["description"] == "第 1 天改为室内展览"


def test_revise_returns_503_when_model_is_unavailable(owned_client, plan_payload, offline_mode, monkeypatch) -> None:
    created = owned_client.post("/api/trip/plan", json=plan_payload()).json()
    pipeline = get_pipeline()

    async def boom(request, plan, candidates, instruction):
        raise LLMUnavailableError("provider_timeout")

    monkeypatch.setattr(pipeline.reviser, "propose", boom)

    response = owned_client.post(
        f"/api/trip/plans/{created['id']}/revise",
        json={"instruction": "换个景点"},
    )

    assert response.status_code == 503
