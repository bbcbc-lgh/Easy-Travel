"""Opening-hours helpers.

AMap returns free text such as "周一至周日 09:00-17:00" or "周二至周日 09:00-16:30，周一闭馆".
We only try to answer one question: *is this venue likely closed on the weekday
of the trip?* Everything else stays as raw text for display.
"""

import re

WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_WEEKDAY_INDEX = {name: index for index, name in enumerate(WEEKDAY_NAMES)}
_CLOSED_WORDS = ("闭馆", "闭园", "休息", "不开放", "停业", "闭门")

_RANGE_PATTERN = re.compile(r"(周[一二三四五六日])\s*(?:至|-|~|到)\s*(周[一二三四五六日])")


def closed_weekdays(opening_hours: str | None) -> set[int] | None:
    """Return the weekdays (0=Monday) that the text says are closed.

    ``None`` means "cannot tell" — which is different from "open every day" and
    must not be treated as safe.
    """
    if not opening_hours:
        return None

    text = opening_hours.strip()
    if not text:
        return None

    closed: set[int] = set()

    for name, index in _WEEKDAY_INDEX.items():
        if re.search(rf"{name}\s*(?:{'|'.join(_CLOSED_WORDS)})", text):
            closed.add(index)

    for match in _RANGE_PATTERN.finditer(text):
        start = _WEEKDAY_INDEX[match.group(1)]
        end = _WEEKDAY_INDEX[match.group(2)]
        if start <= end:
            open_days = set(range(start, end + 1))
        else:  # e.g. 周五至周一
            open_days = set(range(start, 7)) | set(range(0, end + 1))
        closed |= set(range(7)) - open_days

    if not closed and not _RANGE_PATTERN.search(text) and not any(
        word in text for word in _CLOSED_WORDS
    ):
        return None
    return closed


def weekday_name(index: int) -> str:
    return WEEKDAY_NAMES[index % 7]


def is_closed_on(opening_hours: str | None, weekday: int) -> bool | None:
    closed = closed_weekdays(opening_hours)
    if closed is None:
        return None
    return weekday % 7 in closed
