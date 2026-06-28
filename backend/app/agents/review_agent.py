from app.agents.planner_agent import PlannerAgent
from app.models.schemas import PlanQuality, TripPlan, TripPlanRequest


class ReviewAgent:
    def run(self, request: TripPlanRequest, plan: TripPlan, candidate_count: int) -> TripPlan:
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
            day.day_index + 1
            for day in plan.days
            if sum(item.visit_duration for item in day.attractions) > 420
        ]
        checks["daily_duration_reasonable"] = not overloaded_days
        if overloaded_days:
            warnings.append(f"第 {', '.join(map(str, overloaded_days))} 天景点较密集，实际出行时建议删减。")

        unavailable_weather = [item for item in plan.weather_info if not item.forecast_available]
        checks["weather_complete"] = len(plan.weather_info) >= request.days and not unavailable_weather
        if not checks["weather_complete"]:
            notice = next((item.notice for item in unavailable_weather if item.notice), None)
            warnings.append(notice or "天气数据不足，部分日期无法保证查询天气。")

        checks["enough_candidates"] = candidate_count >= min(request.days * 2, 8)
        if not checks["enough_candidates"]:
            warnings.append("候选景点数量偏少，规划结果更适合作为初稿。")

        if plan.budget is None:
            plan.budget = PlannerAgent._calculate_budget(plan.days, request)
        else:
            plan.budget = PlannerAgent._calculate_budget(plan.days, request)

        score = 100
        score -= removed_duplicates * 8
        score -= len(empty_days) * 15
        score -= len(overloaded_days) * 8
        if not checks["weather_complete"]:
            score -= 8
        if not checks["enough_candidates"]:
            score -= 10

        plan.quality = PlanQuality(score=max(score, 0), warnings=warnings, checks=checks)
        return plan

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
