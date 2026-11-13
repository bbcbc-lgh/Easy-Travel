"""Places the traveller insists on: found by name, required in the plan."""

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.model.schemas import Attraction, DayPlan, Location, TripPlan, TripPlanRequest
from src.planning import must_visit
from src.planning.candidates import select_diverse
from src.planning.critic import PlanCritic
from src.service.amap import AMapService, MustVisitNotFound

HANGZHOU = Location(longitude=120.155, latitude=30.274)


def request(**overrides) -> TripPlanRequest:
    payload = {
        "city": "杭州",
        "start_date": date(2026, 12, 1),
        "days": 2,
        "preferences": "自然风光",
        "budget": "中等",
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
    }
    payload.update(overrides)
    return TripPlanRequest(**payload)


def attraction(name: str) -> Attraction:
    return Attraction(
        name=name,
        address="杭州市",
        location=HANGZHOU,
        category="风景名胜;公园广场;公园",
        source="amap",
    )


def day(index: int, names: list[str]) -> DayPlan:
    return DayPlan(
        date="2026-12-01",
        day_index=index,
        description="测试",
        transportation="公共交通",
        accommodation="经济型酒店",
        attractions=[attraction(name) for name in names],
    )


# --- matching ---------------------------------------------------------------


def test_an_exact_name_matches() -> None:
    assert must_visit.matches("西湖", "西湖") is True


def test_a_longer_official_name_still_satisfies_the_query() -> None:
    """The user types "西湖"; the data layer returns "西湖风景名胜区"."""
    assert must_visit.matches("西湖", "西湖风景名胜区") is True
    assert must_visit.matches("西湖风景名胜区", "西湖") is True


def test_a_single_shared_character_is_not_a_match() -> None:
    assert must_visit.matches("西", "西湖") is False


def test_an_unrelated_place_is_not_a_match() -> None:
    assert must_visit.matches("西湖", "灵隐寺") is False


def test_missing_lists_only_the_absent_queries() -> None:
    assert must_visit.missing(["西湖", "灵隐寺"], ["西湖风景名胜区", "雷峰塔"]) == ["灵隐寺"]


def test_duplicated_counts_repeats_of_the_same_place() -> None:
    assert must_visit.duplicated(["西湖"], ["西湖", "西湖风景名胜区"]) == ["西湖"]
    assert must_visit.duplicated(["西湖"], ["西湖", "灵隐寺"]) == []


# --- the critic -------------------------------------------------------------


def build_plan(days: list[DayPlan]) -> TripPlan:
    return TripPlan(
        city="杭州",
        start_date="2026-12-01",
        end_date="2026-12-02",
        days=days,
        overall_suggestions="测试",
    )


def test_a_missing_must_visit_is_an_issue_the_model_can_fix() -> None:
    plan = build_plan([day(0, ["灵隐寺"]), day(1, ["雷峰塔"])])

    critique = PlanCritic().review(request(must_visit=["西湖"]), plan)

    assert any("必去地点「西湖」" in issue for issue in critique.issues)
    assert critique.needs_revision is True


def test_a_present_must_visit_is_not_an_issue() -> None:
    plan = build_plan([day(0, ["西湖风景名胜区"]), day(1, ["灵隐寺"])])

    critique = PlanCritic().review(request(must_visit=["西湖"]), plan)

    assert not any("必去地点" in issue for issue in critique.issues)


def test_a_repeated_must_visit_is_flagged() -> None:
    plan = build_plan([day(0, ["西湖"]), day(1, ["西湖"])])

    critique = PlanCritic().review(request(must_visit=["西湖"]), plan)

    assert any("不止一次" in issue for issue in critique.issues)


def test_no_must_visit_means_no_extra_checks() -> None:
    plan = build_plan([day(0, ["灵隐寺"]), day(1, ["雷峰塔"])])

    critique = PlanCritic().review(request(), plan)

    assert not any("必去地点" in issue for issue in critique.issues)


def test_a_degraded_plan_is_not_asked_to_satisfy_a_must_visit() -> None:
    """The rule planner cannot look a place up, so this check can never pass.

    Flagging it spent one redundant replan and then told the user to "please make
    sure it is scheduled" - an instruction they had already tried to carry out.
    """
    plan = build_plan([day(0, ["灵隐寺"]), day(1, ["雷峰塔"])])
    plan.degraded = True

    critique = PlanCritic().review(request(must_visit=["西湖"]), plan)

    assert not any("必去地点" in issue for issue in critique.issues)
    assert critique.needs_revision is False


def test_a_degraded_plan_says_why_the_must_visit_could_not_be_checked() -> None:
    from src.planning.notices import attach_data_notices

    plan = build_plan([day(0, ["灵隐寺"]), day(1, ["雷峰塔"])])
    plan.degraded = True

    attach_data_notices(plan, request(must_visit=["西湖"]))

    assert any("未参与校验" in notice for notice in plan.data_notices)
    assert any("西湖" in notice for notice in plan.data_notices)


def test_a_live_plan_that_omits_a_must_visit_says_so_plainly() -> None:
    from src.planning.notices import attach_data_notices

    plan = build_plan([day(0, ["灵隐寺"]), day(1, ["雷峰塔"])])

    attach_data_notices(plan, request(must_visit=["西湖"]))

    assert any("没有出现在行程里" in notice for notice in plan.data_notices)


def test_a_satisfied_must_visit_produces_no_notice() -> None:
    from src.planning.notices import attach_data_notices

    plan = build_plan([day(0, ["西湖风景名胜区"]), day(1, ["雷峰塔"])])

    attach_data_notices(plan, request(must_visit=["西湖"]))

    assert not any("必去地点" in notice for notice in plan.data_notices)


def test_editing_a_must_visit_out_of_the_plan_is_reported() -> None:
    """A hand edit can delete the one place the traveller insisted on.

    Generation checks it; the edit path has to check it too, otherwise the promise
    only holds until somebody touches the plan.
    """
    from src.agent.review_agent import ReviewAgent
    from src.api.routes import _score_and_critique
    from src.service.plan_editor import apply_edits

    existing = build_plan([day(0, ["西湖", "灵隐寺"]), day(1, ["雷峰塔"])])
    incoming = existing.model_copy(deep=True)
    incoming.days[0].attractions = [existing.days[0].attractions[1]]

    edited = apply_edits(existing, incoming, request(must_visit=["西湖"]))
    pipeline = SimpleNamespace(review_agent=ReviewAgent(), critic=PlanCritic())
    scored = _score_and_critique(pipeline, request(must_visit=["西湖"]), edited)

    assert any("必去地点" in warning for warning in scored.quality.warnings)
    assert any("西湖" in notice for notice in scored.data_notices)


def test_an_edit_that_keeps_the_must_visit_stays_quiet() -> None:
    from src.agent.review_agent import ReviewAgent
    from src.api.routes import _score_and_critique
    from src.service.plan_editor import apply_edits

    existing = build_plan([day(0, ["西湖", "灵隐寺"]), day(1, ["雷峰塔"])])
    incoming = existing.model_copy(deep=True)

    edited = apply_edits(existing, incoming, request(must_visit=["西湖"]))
    pipeline = SimpleNamespace(review_agent=ReviewAgent(), critic=PlanCritic())
    scored = _score_and_critique(pipeline, request(must_visit=["西湖"]), edited)

    assert not any("必去地点" in warning for warning in scored.quality.warnings)


# --- the candidate list -----------------------------------------------------


def test_a_must_visit_is_never_cut_from_the_prompt_by_the_size_budget() -> None:
    pool = [attraction(f"公园{i}") for i in range(30)]
    pool.append(attraction("西湖"))

    selected = select_diverse(pool, limit=5, pinned=["西湖"])

    assert selected[0].name == "西湖"
    assert len(selected) == 5


# --- the data layer ---------------------------------------------------------


class TestMustVisitLookup:
    def _service(self) -> AMapService:
        return AMapService(Settings(amap_web_service_key="test-key", cache_enabled=False))

    def _poi(self, name: str) -> dict:
        return {"name": name, "type": "风景名胜;公园广场;公园", "location": "120.15,30.27"}

    def test_the_matching_poi_is_picked_over_a_better_ranked_near_miss(self) -> None:
        service = self._service()
        pois = [self._poi("灵隐寺"), self._poi("西湖风景名胜区")]

        picked = service._pick_must_visit(pois, "西湖", request())

        assert picked is not None
        assert picked.name == "西湖风景名胜区"

    def test_a_near_miss_is_not_accepted_as_the_place_asked_for(self) -> None:
        """Substituting a different venue is exactly what a must-visit prevents."""
        service = self._service()

        picked = service._pick_must_visit([self._poi("灵隐寺")], "西湖", request())

        assert picked is None

    def test_an_unfindable_place_fails_loudly_instead_of_dropping_it(self, monkeypatch) -> None:
        service = self._service()

        async def empty_search(**kwargs):
            return []

        monkeypatch.setattr(service, "_search_pois", empty_search)

        with pytest.raises(MustVisitNotFound) as excinfo:
            asyncio.run(service._search_attractions_uncached(request(must_visit=["不存在的地方"])))

        assert excinfo.value.names == ["不存在的地方"]

    def test_a_found_place_is_returned_first(self, monkeypatch) -> None:
        service = self._service()

        async def search(**kwargs):
            if kwargs["keywords"] == ["西湖"]:
                return [self._poi("西湖风景名胜区")]
            return [self._poi("灵隐寺"), self._poi("雷峰塔")]

        monkeypatch.setattr(service, "_search_pois", search)

        found = asyncio.run(service._search_attractions_uncached(request(must_visit=["西湖"])))

        assert found[0].name == "西湖风景名胜区"
        assert [item.name for item in found].count("西湖风景名胜区") == 1
