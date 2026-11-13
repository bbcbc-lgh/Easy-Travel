"""What venue types does the live data layer actually return?

The preference metric maps a venue *type* to a preference axis, so it is only as
good as those mappings. Guessing what AMap calls things produced a metric that
could never see "摄影" (no live type mapped to it) and barely saw "美食". This
command answers the question with data instead of a guess:

    cd backend
    python -m src.cli.poi_types --cities 杭州,北京,上海
    python -m src.cli.poi_types --cities 杭州 --preferences 摄影 --json

It calls the real POI search (so it costs a few requests), prints a frequency
table of the `type` hierarchy's leaf segments, and flags any segment that has no
mapping in `evals.metrics.CATEGORY_AXES` - those are exactly the gaps.
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

if __package__ in {None, ""}:  # allow `python src/cli/poi_types.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.metrics import CATEGORY_AXES
from src.config import Settings
from src.model.schemas import TripPlanRequest
from src.service.amap import AMapService


@dataclass(slots=True)
class TypeReport:
    cities: list[str] = field(default_factory=list)
    segments: Counter[str] = field(default_factory=Counter)
    full_types: Counter[str] = field(default_factory=Counter)
    attractions: int = 0

    def unmapped(self) -> list[str]:
        """Segments that would contribute nothing to any preference axis."""
        return sorted(segment for segment in self.segments if segment not in CATEGORY_AXES)


def leaf_segments(category: str) -> list[str]:
    """Every segment of ``"风景名胜;公园广场;公园"``, so a match anywhere counts."""
    return [part.strip() for part in (category or "").split(";") if part.strip()]


async def collect(settings: Settings, cities: list[str], preferences: str) -> TypeReport:
    service = AMapService(settings)
    report = TypeReport(cities=list(cities))
    for city in cities:
        request = TripPlanRequest(
            city=city,
            start_date=date.today(),
            days=2,
            preferences=preferences,
        )
        attractions = await service.search_attractions(request)
        report.attractions += len(attractions)
        for item in attractions:
            report.full_types[item.category] += 1
            for segment in set(leaf_segments(item.category)):
                report.segments[segment] += 1
    return report


def format_report(report: TypeReport) -> str:
    lines = [
        f"城市        : {', '.join(report.cities)}",
        f"候选景点数  : {report.attractions}",
        "",
        f"{'段':<16}{'出现次数':>8}  映射",
        "-" * 44,
    ]
    for segment, count in report.segments.most_common():
        axes = CATEGORY_AXES.get(segment)
        label = "、".join(sorted(axes)) if axes else "（无映射，计 0）"
        lines.append(f"{segment:<16}{count:>8}  {label}")

    gaps = report.unmapped()
    lines.append("")
    if gaps:
        lines.append(f"没有映射的段（{len(gaps)} 个）：{'、'.join(gaps)}")
        lines.append("这些类型的景点在任何偏好上都不会得分——要么补 CATEGORY_AXES，要么承认该偏好测不到。")
    else:
        lines.append("所有出现过的类型都有映射。")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect the venue types the live data returns")
    parser.add_argument("--cities", default="杭州", help="comma-separated city names")
    parser.add_argument("--preferences", default="历史文化", help="preferences to search with")
    parser.add_argument("--json", action="store_true", help="print the raw counts as JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings()
    if not settings.has_amap:
        print("没有配置 FASTAPI_AMAP_WEB_KEY：这个命令需要真实的高德数据。", file=sys.stderr)
        return 1

    cities = [city.strip() for city in args.cities.split(",") if city.strip()]
    report = _run(collect(settings, cities, args.preferences))

    if args.json:
        payload = {
            "cities": report.cities,
            "attractions": report.attractions,
            "segments": dict(report.segments.most_common()),
            "full_types": dict(report.full_types.most_common()),
            "unmapped": report.unmapped(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(format_report(report))
    return 0


def _run(coro):
    import asyncio

    return asyncio.run(coro)


if __name__ == "__main__":
    raise SystemExit(main())
