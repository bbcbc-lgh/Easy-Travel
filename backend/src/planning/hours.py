"""Opening-hours helpers.

AMap returns free text such as "周一至周日 09:00-17:00" or
"周二至周日 09:00-16:30，周一闭馆". We only answer one question: *is this venue
likely closed on the weekday of the trip?* Everything else stays raw text for
display.

``None`` means "cannot tell", which is different from "open every day" and must
never be treated as safe.
"""

import re

WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

_ALIASES = {
    "周一": 0, "星期一": 0,
    "周二": 1, "星期二": 1,
    "周三": 2, "星期三": 2,
    "周四": 3, "星期四": 3,
    "周五": 4, "星期五": 4,
    "周六": 5, "星期六": 5,
    "周日": 6, "星期日": 6, "周天": 6, "星期天": 6,
}

_CLOSED_WORDS = ("闭馆", "闭园", "休息", "不开放", "停业", "关门", "不营业")
_ALWAYS_OPEN = ("全年无休", "全年开放", "每日开放", "每天开放", "常年开放", "24小时", "全天开放")
_WEEKEND_WORDS = ("周末", "双休", "周六日", "周六周日", "星期六日")

_WEEKDAY_TOKEN = r"(?:星期[一二三四五六日天]|周[一二三四五六日天])"
_RANGE_PATTERN = re.compile(rf"({_WEEKDAY_TOKEN})\s*(?:至|到|-|~|—|－)\s*({_WEEKDAY_TOKEN})")
_TOKEN_PATTERN = re.compile(_WEEKDAY_TOKEN)
_CLAUSE_SPLIT = re.compile(r"[，,。;；\n]+")


def _weekday_index(token: str) -> int:
    return _ALIASES[token]


def _expand(start: int, end: int) -> set[int]:
    if start <= end:
        return set(range(start, end + 1))
    return set(range(start, 7)) | set(range(0, end + 1))


def closed_weekdays(opening_hours: str | None) -> set[int] | None:
    """Return the weekdays (0=Monday) the text says are closed, or ``None``."""
    if not opening_hours:
        return None

    text = opening_hours.strip()
    if not text:
        return None

    closed: set[int] = set()
    open_days: set[int] = set()
    found_signal = False

    for clause in _CLAUSE_SPLIT.split(text):
        clause = clause.strip()
        if not clause:
            continue

        if any(word in clause for word in _CLOSED_WORDS):
            found_signal = True
            for match in _RANGE_PATTERN.finditer(clause):
                closed |= _expand(_weekday_index(match.group(1)), _weekday_index(match.group(2)))
            for token in _TOKEN_PATTERN.findall(clause):
                closed.add(_weekday_index(token))
            if any(word in clause for word in _WEEKEND_WORDS):
                closed |= {5, 6}
            continue

        for match in _RANGE_PATTERN.finditer(clause):
            found_signal = True
            open_days |= _expand(_weekday_index(match.group(1)), _weekday_index(match.group(2)))

    if open_days:
        closed |= set(range(7)) - open_days

    if not found_signal:
        if any(word in text for word in _ALWAYS_OPEN):
            return set()
        return None

    return closed


def weekday_name(index: int) -> str:
    return WEEKDAY_NAMES[index % 7]


def is_closed_on(opening_hours: str | None, weekday: int) -> bool | None:
    closed = closed_weekdays(opening_hours)
    if closed is None:
        return None
    return weekday % 7 in closed
