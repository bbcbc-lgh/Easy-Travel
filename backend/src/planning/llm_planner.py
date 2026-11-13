import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta

from src.model.schemas import (
    Attraction,
    DayDescriptions,
    DayPlan,
    Hotel,
    PlanDecision,
    PlanSkeleton,
    TripPlan,
    TripPlanRequest,
)
from src.planning.budget import calculate_budget
from src.planning.candidates import anchor_location, attraction_lines, candidate_limit, hotel_lines
from src.planning.contracts import CandidatePlaces
from src.planning.scheduler import haversine_meters, optimise_order
from src.service.llm_gateway import LLMGateway, LLMGeneration, LLMUnavailableError
from src.service.logging import log_event

logger = logging.getLogger(__name__)

#: Two-phase generation: the route first, the prose afterwards.
PROMPT_VERSION = "planner-v6"
#: Single-phase generation, kept for `PLAN_TWO_PHASE=false`.
SINGLE_SHOT_PROMPT_VERSION = "planner-v5"
DESCRIPTION_PROMPT_VERSION = "descriptions-v1"

#: The product promise is 1-3 stops a day; the salvage below enforces both ends.
MAX_STOPS_PER_DAY = 3
#: How many stops to put on a day the model left empty (the minimum, not the max:
#: a gap in the model's output is not an invitation to pack the day).
FILL_STOPS_PER_DAY = 2

_PLANNING_RULES = (
    "同一天景点必须彼此靠近：优先挑距酒店 5 公里内的地点，串成一条顺路的线，不要跨区折返；"
    "同一天不要安排两个大型场馆（博物馆/纪念馆/美术馆/展览馆）——两个大馆走不完；"
    "如果当天已经有一个大馆，第二个景点请选公园、街区或市集这类轻松的场所；"
    "候选行里的开放情况要当真：写了「周X闭馆」的地点，那天不要安排；"
    "「开放时间未知」表示需要自行确认，不要把两个这样的点排在同一天；"
    "「票价未知」不等于免费，不要当成 0 元来算预算；"
    "如果某天预报下雨或下雪，那天优先安排室内场所（博物馆/美术馆/展览馆），把户外地点挪到晴天；"
)


class DecisionError(Exception):
    """The model's choices cannot be turned into a grounded itinerary."""


class LLMPlanner:
    """Asks the model *what* to do, then lets the scheduler decide *how*.

    The model only picks names from the candidate lists; order within a day and
    meal selection are deterministic (see ``Scheduler``), so it can neither
    invent places nor produce a zig-zag route.

    With ``PLAN_TWO_PHASE`` on (the default), planning is two calls: a skeleton of
    *which stops on which day*, then prose for the days whose stops are final. A
    14-day trip cannot fit both in one response without hitting the output limit,
    and prose written before trimming describes stops the plan no longer has.
    """

    def __init__(self, gateway: LLMGateway, candidate_search=None):
        self.gateway = gateway
        #: ``async (name, request) -> list[Attraction]``; the bounded retrieval tool.
        self.candidate_search = candidate_search

    @property
    def two_phase(self) -> bool:
        # `getattr` because test doubles stand in for the gateway and only need the
        # one method they are used for.
        settings = getattr(self.gateway, "settings", None)
        return bool(getattr(settings, "plan_two_phase", True))

    @property
    def tool_loop(self) -> bool:
        settings = getattr(self.gateway, "settings", None)
        return bool(getattr(settings, "plan_tool_loop", True))

    async def plan(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None = None,
    ) -> TripPlan:
        if self.two_phase:
            generation, used = await self._skeleton_with_retrieval(request, candidates, feedback)
            return self._hydrate_skeleton(generation, request, used)
        generation = await self._generate(request, candidates, feedback)
        return self._hydrate(generation, request, candidates)

    async def _skeleton_with_retrieval(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None,
    ) -> tuple[LLMGeneration, CandidatePlaces]:
        """Plan, and if the model named a place we did not offer, go and find it.

        This is the whole tool loop, deliberately: one round, only when the failure
        is "you did not give me that place", and only for names the server can
        resolve. It turns a real observed failure ("attraction '养心殿' is not in
        the candidate list" -> whole trip degrades to the rule engine) into one
        extra lookup.
        """
        try:
            return await self._generate_skeleton(request, candidates, feedback), candidates
        except LLMUnavailableError as exc:
            names = _unknown_attraction_names(exc.detail) if exc.reason == "schema_invalid" else []
            if not names or not self.tool_loop or self.candidate_search is None:
                raise

        added = await self._lookup_places(names, request, candidates)
        if not added:
            raise LLMUnavailableError("candidate_lookup_failed", attempts=1, detail=", ".join(names))

        enriched = CandidatePlaces(
            attractions=[*candidates.attractions, *added],
            hotels=candidates.hotels,
            weather=candidates.weather,
        )
        log_event(
            logger,
            "planner.candidate_expanded",
            level=logging.INFO,
            city=request.city,
            requested=names,
            added=[item.name for item in added],
        )
        return await self._generate_skeleton(request, enriched, feedback), enriched

    async def _lookup_places(
        self,
        names: list[str],
        request: TripPlanRequest,
        candidates: CandidatePlaces,
    ) -> list[Attraction]:
        search = self.candidate_search
        if search is None:  # caller checks this, but the type does not know
            return []
        known = {_name_key(item.name) for item in candidates.attractions}
        added: list[Attraction] = []
        for name in names[:3]:
            for item in await search(name, request):
                key = _name_key(item.name)
                if key in known:
                    continue
                known.add(key)
                added.append(item)
                if len(added) >= 5:
                    return added
        return added

    async def describe(
        self,
        plan: TripPlan,
        request: TripPlanRequest,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> TripPlan:
        """Write the day prose for a plan whose stops are final.

        A failure here must not throw away the route: the structure is what the
        user acts on, so a description failure falls back to a plain sentence
        instead of degrading the whole plan to the rule engine.

        With ``on_delta``, the prose is streamed as it is generated - this is the
        phase worth streaming, because by then the user is looking at the page and
        the text is the only thing still missing.
        """
        if not self.two_phase or plan.degraded:
            return plan

        kwargs = {
            "prompt_version": DESCRIPTION_PROMPT_VERSION,
            "validate": _build_description_validator(plan),
            "response_schema": DayDescriptions,
            "budget_seconds": self._budget_for(request),
        }
        system_prompt = _description_system_prompt()
        user_prompt = _description_user_prompt(plan)
        try:
            if on_delta is not None:
                generation = await self.gateway.generate_json_stream(
                    system_prompt, user_prompt, on_delta=on_delta, **kwargs
                )
            else:
                generation = await self.gateway.generate_json(system_prompt, user_prompt, **kwargs)
        except LLMUnavailableError as exc:
            log_event(
                logger,
                "planner.description_failed",
                level=logging.WARNING,
                reason=exc.reason,
                attempts=exc.attempts,
                prompt_version=DESCRIPTION_PROMPT_VERSION,
                city=plan.city,
                days=len(plan.days),
            )
            return _fill_template_descriptions(plan)

        descriptions: dict[int, str] = {}
        value: DayDescriptions = generation.value
        for item in value.days:
            descriptions[item.day_index] = item.description
        log_event(
            logger,
            "planner.described",
            prompt_version=DESCRIPTION_PROMPT_VERSION,
            model=generation.profile,
            attempts=generation.attempts,
            city=plan.city,
            days=len(plan.days),
            elapsed_ms=generation.elapsed_ms,
        )
        return _apply_descriptions(plan, descriptions)

    # --- phase 1: the route ---------------------------------------------------

    async def _generate_skeleton(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None,
    ) -> LLMGeneration:
        system_prompt = (
            "你是行程规划专家。只能从用户给出的候选地点中选择，不要编造任何地点。\n"
            '只输出 JSON：{"days":[{"day_index":0,"attractions":["景点名称"],"hotel":"酒店名称"}],'
            '"overall_suggestions":"整体建议"}\n'
            f"规则：days 必须恰好覆盖 0 到 {request.days - 1}；每天 1-3 个景点，所有景点不得重复；"
            f"{_PLANNING_RULES}"
            "不要输出当日文案、坐标、价格、天气或 Markdown 代码块。"
        )
        return await self.gateway.generate_json(
            system_prompt,
            self._candidate_prompt(request, candidates, feedback),
            prompt_version=PROMPT_VERSION,
            validate=_build_skeleton_validator(request, candidates),
            response_schema=PlanSkeleton,
            budget_seconds=self._budget_for(request),
        )

    def _hydrate_skeleton(
        self,
        generation: LLMGeneration,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
    ) -> TripPlan:
        skeleton: PlanSkeleton = generation.value
        slots, hotels = _collect_selection(skeleton.days, candidates, request.days)
        if not any(slots):
            raise DecisionError("skeleton_had_no_usable_place")

        days: list[DayPlan] = []
        for day_index in range(request.days):
            days.append(_build_day(day_index, request, hotels[day_index], slots[day_index], description=""))

        plan = TripPlan(
            city=request.city,
            start_date=request.start_date.isoformat(),
            end_date=request.resolved_end_date.isoformat(),
            days=days,
            weather_info=list(candidates.weather),
            overall_suggestions=skeleton.overall_suggestions or _default_suggestions(request),
            budget=calculate_budget(days, request),
        )
        log_event(
            logger,
            "planner.completed",
            source="llm",
            prompt_version=PROMPT_VERSION,
            model=generation.profile,
            attempts=generation.attempts,
            repaired=generation.repaired,
            elapsed_ms=generation.elapsed_ms,
            city=request.city,
            days=request.days,
            candidate_attractions=len(candidates.attractions),
            phase="skeleton",
        )
        return plan

    # --- single-phase fallback ------------------------------------------------

    async def _generate(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None,
    ) -> LLMGeneration:
        system_prompt = (
            "你是行程规划专家。只能从用户给出的候选地点中选择，不要编造任何地点。\n"
            '只输出 JSON：{"days":[{"day_index":0,"description":"当日安排与安排理由",'
            '"attractions":["景点名称"],"hotel":"酒店名称"}],'
            '"overall_suggestions":"整体建议"}\n'
            f"规则：days 必须恰好覆盖 0 到 {request.days - 1}；每天 1-3 个景点，所有景点不得重复；"
            f"{_PLANNING_RULES}"
            "description 只写活动类型、片区和节奏（例如「上午看展，午后在湖边散步，节奏轻松」），"
            "不要出现任何具体场所名称——景点、商场、餐厅、酒店一律不提，因为服务端可能在后处理里调整当天的点，"
            "写了名字就会和实际行程对不上；"
            "hotel 只能取候选酒店；不要输出坐标、价格、天气或 Markdown 代码块。"
        )
        return await self.gateway.generate_json(
            system_prompt,
            self._candidate_prompt(request, candidates, feedback),
            prompt_version=SINGLE_SHOT_PROMPT_VERSION,
            validate=self._build_validator(request, candidates),
            response_schema=PlanDecision,
            budget_seconds=self._budget_for(request),
        )

    @staticmethod
    def _candidate_prompt(
        request: TripPlanRequest,
        candidates: CandidatePlaces,
        feedback: list[str] | None,
    ) -> str:
        weather_summary = [
            f"{item.date} {item.day_weather} {item.night_temp}~{item.day_temp}℃" for item in candidates.weather
        ]
        anchor = anchor_location(candidates.hotels)
        attraction_block = (
            "\n".join(
                attraction_lines(
                    candidates.attractions,
                    anchor,
                    limit=candidate_limit(request.days),
                    pinned=request.must_visit,
                )
            )
            or "（无）"
        )
        hotel_block = "\n".join(hotel_lines(candidates.hotels, anchor)) or "（无）"
        user_prompt = (
            f"目的地：{request.city}\n"
            f"日期：{request.start_date} 到 {request.end_date}，共 {request.days} 天\n"
            f"偏好：{request.preferences}\n"
            f"预算：{request.budget}\n"
            f"交通：{request.transportation}\n"
            f"住宿：{request.accommodation}\n"
            f"候选景点（名称 | 类型 | 门票 | 建议时长 | 开放情况 | 距酒店）：\n{attraction_block}\n"
            f"候选酒店（名称 | 类型 | 房价 | 距酒店）：\n{hotel_block}\n"
            f"天气：{json.dumps(weather_summary, ensure_ascii=False)}\n"
        )
        if feedback:
            user_prompt += "上一版行程存在以下问题，请在本版中修正：\n" + "\n".join(f"- {item}" for item in feedback)
        if request.must_visit:
            user_prompt += f"必去地点（每个都要安排，且只安排一次）：{'、'.join(request.must_visit)}\n"
        return user_prompt

    def _hydrate(
        self,
        generation: LLMGeneration,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
    ) -> TripPlan:
        decision: PlanDecision = generation.value
        slots, hotels = _collect_selection(decision.days, candidates, request.days)
        if not any(slots):
            raise DecisionError("decision_had_no_usable_place")
        by_index = {day.day_index: day for day in decision.days}

        days: list[DayPlan] = []
        for day_index in range(request.days):
            description = by_index.get(day_index)
            days.append(
                _build_day(
                    day_index,
                    request,
                    hotels[day_index],
                    slots[day_index],
                    description=description.description if description is not None else "",
                )
            )

        plan = TripPlan(
            city=request.city,
            start_date=request.start_date.isoformat(),
            end_date=request.resolved_end_date.isoformat(),
            days=days,
            weather_info=list(candidates.weather),
            overall_suggestions=decision.overall_suggestions or _default_suggestions(request),
            budget=calculate_budget(days, request),
        )
        log_event(
            logger,
            "planner.completed",
            source="llm",
            prompt_version=SINGLE_SHOT_PROMPT_VERSION,
            model=generation.profile,
            attempts=generation.attempts,
            repaired=generation.repaired,
            elapsed_ms=generation.elapsed_ms,
            city=request.city,
            days=request.days,
            candidate_attractions=len(candidates.attractions),
            phase="single",
        )
        return plan

    # --- validators -----------------------------------------------------------

    def _build_validator(
        self,
        request: TripPlanRequest,
        candidates: CandidatePlaces,
    ) -> Callable[[dict], PlanDecision]:
        def validate(payload: dict) -> PlanDecision:
            decision = PlanDecision.model_validate(payload)
            _check_selections(
                [(day.attractions, day.hotel) for day in decision.days],
                candidates,
                request,
            )
            return decision

        return validate

    def _budget_for(self, request: TripPlanRequest) -> float:
        """A 14-day trip needs more than the 150s a 3-day trip takes.

        The deadline covers every profile and retry, so a long trip that is not
        given more time will be cut off mid-way and degrade to the rule planner -
        which is exactly what happened before this existed.
        """
        return min(150.0 + 20.0 * request.days, 300.0)


def _build_skeleton_validator(
    request: TripPlanRequest,
    candidates: CandidatePlaces,
) -> Callable[[dict], PlanSkeleton]:
    def validate(payload: dict) -> PlanSkeleton:
        skeleton = PlanSkeleton.model_validate(payload)
        _check_selections([(day.attractions, day.hotel) for day in skeleton.days], candidates, request)
        return skeleton

    return validate


def _unknown_attraction_names(detail: str) -> list[str]:
    """Read back the place names a schema complaint says we did not offer."""
    return [match.group(1) for match in re.finditer(r"attraction '([^']+)' is not in the candidate list", detail or "")]


def _check_selections(
    selections: list[tuple[list[str], str | None]],
    candidates: CandidatePlaces,
    request: TripPlanRequest,
) -> None:
    """Reject only what the server cannot repair by itself.

    An unknown attraction name is rejected so the caller can go and look it up
    (see ``_skeleton_with_retrieval``). Everything else - an empty day, the wrong
    number of days, a repeated stop, four stops in one day, a hotel we never
    offered - is repaired deterministically in :func:`_collect_selection`. Those
    shapes used to be rejected, and one wobble in the model's output degraded the
    whole trip to the rule planner: it was the most common cause of degradation on
    short trips (2 of 20 in the last live run).
    """
    attraction_index = _index_by_name(candidates.attractions)
    for _position, (names, _hotel) in enumerate(selections):
        for name in names:
            if _name_key(name) not in attraction_index:
                raise ValueError(f"attraction {name!r} is not in the candidate list")


def _collect_selection(
    days_payload,
    candidates: CandidatePlaces,
    total_days: int,
) -> tuple[list[list[Attraction]], list[Hotel | None]]:
    """Turn whatever the model returned into one slot per day, filling the gaps.

    Every rule here is deterministic and uses only the candidate pool the caller
    already paid for - nothing is invented:

    * an out-of-range or repeated ``day_index`` falls back to list position;
    * unknown names are dropped (they were rejected earlier if they mattered);
    * more than three stops in a day drops the tail;
    * a stop that appears on two days stays on the first;
    * an empty day is filled from the nearest unused candidates, and if the pool is
      spent, by moving one stop from the fullest day.
    """
    attraction_index = _index_by_name(candidates.attractions)
    hotel_index = _index_by_name(candidates.hotels)
    default_hotel = candidates.hotels[0] if candidates.hotels else None

    by_index: dict[int, object] = {}
    for position, day in enumerate(days_payload):
        index = getattr(day, "day_index", position)
        if not isinstance(index, int) or not 0 <= index < total_days:
            index = position if position < total_days else -1
        if index < 0 or index in by_index:
            continue
        by_index[index] = day

    seen: set[str] = set()
    slots: list[list[Attraction]] = []
    hotels: list[Hotel | None] = []
    for day_index in range(total_days):
        payload = by_index.get(day_index)
        chosen: list[Attraction] = []
        if payload is not None:
            for name in getattr(payload, "attractions", []):
                item = attraction_index.get(_name_key(name))
                if item is None:
                    continue
                key = _name_key(item.name)
                if key in seen or len(chosen) >= MAX_STOPS_PER_DAY:
                    continue
                seen.add(key)
                chosen.append(item)
        slots.append(chosen)
        hotel_name = getattr(payload, "hotel", None) if payload is not None else None
        hotels.append(_resolve_hotel(hotel_name, hotel_index, default_hotel))

    _fill_empty_days(slots, candidates, hotels)
    return slots, hotels


def _fill_empty_days(
    slots: list[list[Attraction]],
    candidates: CandidatePlaces,
    hotels: list[Hotel | None],
) -> None:
    """No day is left without a stop while the pool still has one to give."""
    used = {id(item) for slot in slots for item in slot}
    pool = [item for item in candidates.attractions if id(item) not in used]

    for day_index, slot in enumerate(slots):
        if slot:
            continue
        hotel = hotels[day_index] if day_index < len(hotels) else None
        anchor = hotel.location if hotel is not None else None
        if pool:
            pool.sort(key=lambda item: haversine_meters(anchor, item.location))
            take = pool[:FILL_STOPS_PER_DAY]
            slots[day_index] = list(take)
            pool = pool[len(take) :]
            continue
        donor = max(range(len(slots)), key=lambda index: len(slots[index]))
        if len(slots[donor]) > 1:
            slots[day_index] = [slots[donor].pop()]


def _build_description_validator(plan: TripPlan) -> Callable[[dict], DayDescriptions]:
    """Only checks that every day is described.

    Cross-day leaks are *not* rejected here. `_apply_descriptions` already replaces
    a day's prose when it names another day's stop, so rejecting the whole response
    would pay for a repair round and, if that failed too, throw away the other days'
    good sentences along with the bad one. One place enforces the invariant; the
    rest of the call is allowed to succeed.
    """

    def validate(payload: dict) -> DayDescriptions:
        value = DayDescriptions.model_validate(payload)
        indices = sorted(item.day_index for item in value.days)
        if indices != list(range(len(plan.days))):
            raise ValueError(f"days must cover 0..{len(plan.days) - 1} exactly once")
        return value

    return validate


def _description_system_prompt() -> str:
    return (
        "你是旅行编辑。行程的景点和顺序已经定稿，请为每一天写一段当日说明。\n"
        '只输出 JSON：{"days":[{"day_index":0,"description":"..."}]}\n'
        "规则：\n"
        "1. days 必须恰好覆盖行程里的每一天，day_index 与给定的一致；\n"
        "2. 每天 1-2 句，交代节奏和活动类型（上午看展、午后沿湖散步、傍晚登高看夜景），不要复述门票或预算；\n"
        "3. 可以提到当天的景点名，但只能提当天自己的景点，不要提别的天的地点；\n"
        "4. 不要新增任何地点，不要写 Markdown，不要输出解释。"
    )


def _description_user_prompt(plan: TripPlan) -> str:
    lines = [f"城市：{plan.city}，共 {len(plan.days)} 天", ""]
    for day in plan.days:
        stops = "、".join(item.name for item in day.attractions) or "无"
        categories = "、".join(sorted({item.category for item in day.attractions})) or "无"
        lines.append(f"- 第 {day.day_index + 1} 天（{day.date}）：{stops}（{categories}）")
    return "\n".join(lines)


def _apply_descriptions(plan: TripPlan, descriptions: dict[int, str]) -> TripPlan:
    """Attach prose, dropping any sentence that contradicts the route.

    The validator already rejects cross-day leaks, but this is a user-visible
    invariant that also has to hold if a provider hands back something the
    validator could not see (a repair round, a cached body, a future caller that
    skips validation). One stop's prose naming another day's stop is exactly the
    contradiction this project removed once already, so it is enforced at the
    point of writing, not only at the point of reading.
    """
    stops_by_day = {day.day_index: [item.name for item in day.attractions] for day in plan.days}
    for day in plan.days:
        text = descriptions.get(day.day_index, "")
        if text and not _leaks_other_day(text, day.day_index, stops_by_day):
            day.description = text
        else:
            day.description = _template_description(day)
    return plan


def _leaks_other_day(text: str, day_index: int, stops_by_day: dict[int, list[str]]) -> bool:
    """Whether a day's prose names a stop that belongs to another day.

    This day's own stop names are removed from the text first. Without that,
    "天安门广场" (this day) contains "天安门" (another day) and the check fires on a
    perfectly correct sentence - a false alarm that would replace good prose.
    """
    haystack = "".join(text.split())
    for name in stops_by_day.get(day_index, []):
        key = "".join(name.split())
        if len(key) >= 2:
            haystack = haystack.replace(key, "")
    for other_index, names in stops_by_day.items():
        if other_index == day_index:
            continue
        for name in names:
            key = "".join(name.split())
            if len(key) >= 2 and key in haystack:
                return True
    return False


def _fill_template_descriptions(plan: TripPlan) -> TripPlan:
    for day in plan.days:
        if not day.description:
            day.description = _template_description(day)
    return plan


def _template_description(day: DayPlan) -> str:
    """The safe fallback: still says what the day holds, without pretending to style."""
    if not day.attractions:
        return "今天不安排固定景点，按体力和天气自由走动。"
    names = "、".join(item.name for item in day.attractions)
    return f"这一天按就近顺序游览 {names}，站间留出步行和休息的余量。"


def _build_day(
    day_index: int,
    request: TripPlanRequest,
    hotel: Hotel | None,
    attractions: list[Attraction],
    description: str,
) -> DayPlan:
    return DayPlan(
        date=(request.start_date + timedelta(days=day_index)).isoformat(),
        day_index=day_index,
        description=description,
        transportation=request.transportation,
        accommodation=request.accommodation,
        hotel=hotel,
        attractions=optimise_order(hotel.location if hotel else None, attractions),
    )


def _resolve_attractions(names: list[str], index: dict) -> list[Attraction]:
    resolved: list[Attraction] = []
    for name in names:
        attraction = index.get(_name_key(name))
        if attraction is None:
            raise DecisionError(f"unknown_attraction:{name}")
        resolved.append(attraction)
    return resolved


def _resolve_hotel(name: str | None, index: dict, default: Hotel | None) -> Hotel | None:
    if not name:
        return default
    return index.get(_name_key(name)) or default


def _default_suggestions(request: TripPlanRequest) -> str:
    return f"建议使用{request.transportation}衔接当天景点，出发前确认开放时间与天气。"


def _name_key(name: str) -> str:
    return "".join(name.split()).lower()


def _index_by_name(items) -> dict:
    index = {}
    for item in items:
        index.setdefault(_name_key(item.name), item)
    return index
