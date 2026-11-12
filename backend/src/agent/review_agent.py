from src.model.schemas import Attraction, Hotel, PlanQuality, TripPlan, TripPlanRequest
from src.planning.budget import calculate_budget


class ReviewAgent:
    """Scores a plan from facts the pipeline can actually verify.

    The score answers one question: *how much of this itinerary can the user
    trust?* A rule-engine fallback, unknown prices or placeholder places must
    lower it — a template plan never deserves 100.
    """

    def run(self, request: TripPlanRequest, plan: TripPlan, candidate_count: int | None = None) -> TripPlan:
        warnings: list[str] = []
        checks: dict[str, bool] = {}

        removed_duplicates = self._remove_duplicate_attractions(plan)
        checks["no_duplicate_attractions"] = removed_duplicates == 0
        if removed_duplicates:
            warnings.append(f"已自动移除 {removed_duplicates} 个重复景点。")

        empty_days = [day.day_index + 1 for day in plan.days if not day.attractions]
        checks["all_days_have_attractions"] = not empty_days
        if empty_days:
            warnings.append(f"第 {', '.join(map(str, empty_days))} 天暂无可用景点，建议手动补充或缩短天数。")

        overloaded_days = [
            day.day_index + 1 for day in plan.days if sum(item.visit_duration for item in day.attractions) > 420
        ]
        checks["daily_duration_reasonable"] = not overloaded_days
        if overloaded_days:
            warnings.append(f"第 {', '.join(map(str, overloaded_days))} 天景点较密集，实际出行时建议删减。")

        unavailable_weather = [item for item in plan.weather_info if not item.forecast_available]
        checks["weather_complete"] = len(plan.weather_info) >= request.days and not unavailable_weather
        if not checks["weather_complete"]:
            notice = next((item.notice for item in unavailable_weather if item.notice), None)
            warnings.append(notice or "天气数据不足，部分日期无法保证查询天气。")

        if candidate_count is None:
            # Editing an existing plan: the candidate pool is no longer known,
            # so this check cannot judge anything — leave it neutral.
            checks["enough_candidates"] = True
        else:
            checks["enough_candidates"] = candidate_count >= min(request.days * 2, 8)
            if not checks["enough_candidates"]:
                warnings.append("候选景点数量偏少，规划结果更适合作为初稿。")

        sparse_days = [day.day_index + 1 for day in plan.days if len(day.attractions) < 2]
        checks["daily_content_sufficient"] = not sparse_days
        if sparse_days:
            warnings.append(
                f"\u7b2c {', '.join(map(str, sparse_days))} \u5929\u666f\u70b9\u5b89\u6392\u504f\u5c11\uff0c\u5efa\u8bae\u8865\u5145\u4e3a\u534a\u5929\u4f11\u95f2\u3001\u7279\u8272\u4f53\u9a8c\u6216\u8c03\u6574\u65c5\u884c\u5929\u6570\u3002"
            )

        sample_places: list[object] = [item for day in plan.days for item in day.attractions if item.source == "sample"]
        sample_places.extend(day.hotel for day in plan.days if day.hotel and day.hotel.source == "sample")
        checks["place_data_is_live"] = not sample_places
        if sample_places:
            warnings.append(
                "\u666f\u70b9\u3001\u9910\u996e\u6216\u4f4f\u5bbf\u672a\u83b7\u5f97\u5b9e\u65f6\u5730\u70b9\u6570\u636e\uff0c\u9875\u9762\u5df2\u6309\u6f14\u793a\u6570\u636e\u6807\u8bb0\uff0c\u8bf7\u52ff\u76f4\u63a5\u7528\u4e8e\u9884\u8ba2\u6216\u5bfc\u822a\u3002"
            )

        checks["planned_by_model"] = not plan.degraded
        if plan.degraded:
            warnings.append(
                f"本次行程由规则引擎生成（原因：{plan.degraded_reason or 'model_unavailable'}），"
                "未经 AI 规划，仅供参考。"
            )

        estimated_count, unknown_count = self._price_provenance(plan)
        checks["prices_are_confirmed"] = unknown_count == 0
        if unknown_count:
            warnings.append(f"{unknown_count} 项价格暂无法确认，页面已隐藏具体金额，以现场为准。")
        if estimated_count:
            warnings.append(f"{estimated_count} 项价格为规则估算，实际以现场为准。")

        plan.budget = calculate_budget(plan.days, request)

        score = 100
        score -= removed_duplicates * 8
        score -= len(empty_days) * 15
        score -= len(overloaded_days) * 8
        if not checks["weather_complete"]:
            score -= 8
        if candidate_count is not None and not checks["enough_candidates"]:
            score -= 10
        score -= len(sparse_days) * 8
        if sample_places:
            score -= 18
        score -= min(unknown_count * 4, 16)
        if estimated_count:
            score = min(score, 95)
        if plan.degraded:
            score -= 35
        score = max(score, 0)
        if plan.degraded:
            score = min(score, 60)

        plan.quality = PlanQuality(score=score, warnings=warnings, checks=checks)
        return plan

    @staticmethod
    def _price_provenance(plan: TripPlan) -> tuple[int, int]:
        attractions: list[Attraction] = [item for day in plan.days for item in day.attractions]
        hotels: list[Hotel] = [day.hotel for day in plan.days if day.hotel]
        items = [*attractions, *hotels]
        estimated = sum(1 for item in items if item.price_source == "estimated")
        unknown = sum(1 for item in items if item.price_source == "unknown")
        return estimated, unknown

    @staticmethod
    def _remove_duplicate_attractions(plan: TripPlan) -> int:
        seen: set[str] = set()
        removed = 0
        for day in plan.days:
            unique = []
            for attraction in day.attractions:
                key = f"{attraction.name}|{attraction.address}".strip().lower()
                if key in seen:
                    removed += 1
                    continue
                seen.add(key)
                unique.append(attraction)
            day.attractions = unique
        return removed
