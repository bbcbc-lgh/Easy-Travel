from src.model.schemas import TripPlan


def attach_data_notices(plan: TripPlan) -> TripPlan:
    """Record, on the plan itself, that some data is only demonstrative."""
    notices: list[str] = []
    place_items = [item for day in plan.days for item in [*day.attractions, *day.meals] if item.source == "sample"]
    place_items.extend(day.hotel for day in plan.days if day.hotel and day.hotel.source == "sample")
    if place_items:
        notices.append("\u5b9e\u65f6\u5730\u70b9\u6570\u636e\u4e0d\u8db3\uff1a\u5f53\u524d\u5c55\u793a\u7684\u6a21\u62df\u5019\u9009\u4ec5\u4f9b\u6f14\u793a\uff0c\u4e0d\u53ef\u7528\u4e8e\u5bfc\u822a\u6216\u9884\u8ba2\u3002")
    if any(not weather.forecast_available for weather in plan.weather_info):
        notices.append("\u884c\u7a0b\u542b\u6709\u65e0\u6cd5\u786e\u8ba4\u7684\u5929\u6c14\u65e5\u671f\uff0c\u8bf7\u51fa\u884c\u524d\u518d\u6b21\u67e5\u8be2\u3002")
    plan.data_notices = notices
    return plan
