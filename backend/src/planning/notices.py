from src.model.schemas import TripPlan, TripPlanRequest
from src.planning import must_visit


def attach_data_notices(plan: TripPlan, request: TripPlanRequest | None = None) -> TripPlan:
    """Record, on the plan itself, that some data is only demonstrative."""
    notices: list[str] = []
    place_items: list[object] = [item for day in plan.days for item in day.attractions if item.source == "sample"]
    place_items.extend(day.hotel for day in plan.days if day.hotel and day.hotel.source == "sample")
    if place_items:
        notices.append(
            "\u5b9e\u65f6\u5730\u70b9\u6570\u636e\u4e0d\u8db3\uff1a\u5f53\u524d\u5c55\u793a\u7684\u6a21\u62df\u5019\u9009\u4ec5\u4f9b\u6f14\u793a\uff0c\u4e0d\u53ef\u7528\u4e8e\u5bfc\u822a\u6216\u9884\u8ba2\u3002"
        )
    if any(not weather.forecast_available for weather in plan.weather_info):
        notices.append(
            "\u884c\u7a0b\u542b\u6709\u65e0\u6cd5\u786e\u8ba4\u7684\u5929\u6c14\u65e5\u671f\uff0c\u8bf7\u51fa\u884c\u524d\u518d\u6b21\u67e5\u8be2\u3002"
        )
    notices.extend(_must_visit_notices(plan, request))
    plan.data_notices = notices
    return plan


def _must_visit_notices(plan: TripPlan, request: TripPlanRequest | None) -> list[str]:
    """Say plainly when a must-visit could not be honoured, and why.

    This is the honest half of the must-visit feature: the rule planner and the
    offline sample data have no way to look a place up, so a plan built without
    live data may simply not contain it. Reporting that is better than a warning
    asking the user to "please schedule it", which they already tried to do.
    """
    if request is None or not request.must_visit:
        return []

    planned = [item.name for day in plan.days for item in day.attractions]
    absent = must_visit.missing(request.must_visit, planned)
    if not absent:
        return []

    names = "、".join(f"「{name}」" for name in absent)
    if plan.degraded:
        return [
            f"必去地点 {names} 未参与校验：本次行程由规则引擎生成，无法检索实时地点数据。"
            "配置地图 Key 并使用模型规划后再试，才能确保它被安排进去。"
        ]
    return [f"必去地点 {names} 没有出现在行程里，建议手动调整或换个写法重新生成。"]
