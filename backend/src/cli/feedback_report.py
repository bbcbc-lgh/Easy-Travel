"""Summarise the "this stop is wrong" notes collected from the result page.

    cd backend
    python -m src.cli.feedback_report
    python -m src.cli.feedback_report --notes 10

Collected feedback is only worth the feedback it records: this is the command that
turns the rows into something a human can act on - which kind of mistake the
planner makes most often, and in which city.
"""

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:  # allow `python src/cli/feedback_report.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.config import settings
from src.service.database import TripPlanRepository

REASON_LABELS = {
    "too_packed": "排得太满",
    "wrong_place": "地点不合适",
    "closed": "当时不开放",
    "too_far": "距离太远",
    "other": "其他",
}
TARGET_LABELS = {"attraction": "景点", "meal": "餐饮", "hotel": "酒店"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise plan feedback")
    parser.add_argument("--notes", type=int, default=5, help="how many free-text notes to print")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repository = TripPlanRepository(settings)

    rows = repository.feedback_summary()
    if not rows:
        print("还没有反馈。在结果页点景点旁边的“!”按钮就能记一条。")
        return 0

    total = sum(row["count"] for row in rows)
    print(f"共 {total} 条反馈\n")
    print(f"{'问题':<10} {'对象':<6} {'条数':>4}")
    print("-" * 24)
    for row in rows:
        reason = REASON_LABELS.get(row["reason"], row["reason"])
        target = TARGET_LABELS.get(row["target"], row["target"])
        print(f"{reason:<10} {target:<6} {row['count']:>4}")

    notes = repository.feedback_notes(limit=max(args.notes, 0))
    if notes:
        print(f"\n最近的说明（{len(notes)} 条）：")
        for note in notes:
            city = note["city"] or "?"
            reason = REASON_LABELS.get(note["reason"], note["reason"])
            print(f"- [{city} 第{note['day_index'] + 1}天] {note['target_name']}（{reason}）：{note['note']}")

    most_common = rows[0]
    print(
        f"\n最常见的问题：{REASON_LABELS.get(most_common['reason'], most_common['reason'])}"
        f"（{most_common['count']} 条）。先修这个。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
