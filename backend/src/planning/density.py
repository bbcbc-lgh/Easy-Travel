"""How much of a day a stop actually consumes.

Walking minutes are a poor proxy: a national museum and a city park can both be
"90 minutes" on paper while the museum eats a morning with queues and security.
This module gives each stop a *load* instead, and a day has a budget.
"""

from src.model.schemas import Attraction, DayPlan

DAILY_LOAD_LIMIT = 3.5

# Match order matters: museums before parks before streets.
_HEAVY_TERMS = ("博物馆", "纪念馆", "美术馆", "展览馆", "科技馆", "故宫", "宫", "陵", "遗址", "版本馆")
_MEDIUM_TERMS = ("风景", "公园", "山", "湖", "湿地", "植物园", "广场", "寺", "塔")
_LIGHT_TERMS = ("街区", "老街", "市集", "市场", "步行街", "商圈", "购物")

HEAVY_LOAD = 2.0
MEDIUM_LOAD = 1.0
LIGHT_LOAD = 0.5
DEFAULT_LOAD = 1.0


def attraction_load(attraction: Attraction) -> float:
    haystack = f"{attraction.name}{attraction.category}"
    if any(term in haystack for term in _HEAVY_TERMS):
        return HEAVY_LOAD
    if any(term in haystack for term in _MEDIUM_TERMS):
        return MEDIUM_LOAD
    if any(term in haystack for term in _LIGHT_TERMS):
        return LIGHT_LOAD
    return DEFAULT_LOAD


def day_load(day: DayPlan) -> float:
    return round(sum(attraction_load(item) for item in day.attractions), 1)


def overloaded_days(plan) -> list[tuple[int, float]]:
    """(day_index, load) for days that exceed the budget."""
    return [(day.day_index, load) for day in plan.days if (load := day_load(day)) > DAILY_LOAD_LIMIT]


def describe_load(day: DayPlan) -> str:
    names = "、".join(item.name for item in day.attractions)
    return f"{names}（约 {day_load(day):.1f} 个单位，单日建议上限 {DAILY_LOAD_LIMIT}）"
