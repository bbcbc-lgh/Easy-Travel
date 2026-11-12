import contextlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.config import Settings
from src.model.schemas import PlanFeedback, TripPlan, TripPlanRequest
from src.service.migrations import run_migrations

LEGACY_OWNER = "legacy"


class TripPlanRepository:
    def __init__(self, settings: Settings):
        self.database_path = self._resolve_database_path(settings.database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def init_schema(self) -> None:
        """Bring the store up to date; migrations own the schema, not this class."""
        with self._connect() as connection:
            run_migrations(connection)

    def save_plan(self, request: TripPlanRequest, plan: TripPlan, owner_id: str) -> TripPlan:
        plan_id = plan.id or uuid4().hex
        now = self._now()
        plan.id = plan_id
        payload = plan.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO trip_plans (
                    id, owner_id, city, start_date, end_date, days,
                    request_json, plan_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    city = excluded.city,
                    start_date = excluded.start_date,
                    end_date = excluded.end_date,
                    days = excluded.days,
                    request_json = excluded.request_json,
                    plan_json = excluded.plan_json,
                    updated_at = excluded.updated_at
                """,
                (
                    plan_id,
                    owner_id,
                    plan.city,
                    plan.start_date,
                    plan.end_date,
                    len(plan.days),
                    request.model_dump_json(),
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return plan

    def update_plan(self, plan_id: str, plan: TripPlan, owner_id: str) -> TripPlan | None:
        if self.get_plan(plan_id, owner_id) is None:
            return None
        plan.id = plan_id
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE trip_plans
                SET city = ?, start_date = ?, end_date = ?, days = ?,
                    plan_json = ?, updated_at = ?
                WHERE id = ? AND owner_id = ?
                """,
                (
                    plan.city,
                    plan.start_date,
                    plan.end_date,
                    len(plan.days),
                    plan.model_dump_json(),
                    now,
                    plan_id,
                    owner_id,
                ),
            )
        return plan if cursor.rowcount else None

    def get_plan(self, plan_id: str, owner_id: str) -> TripPlan | None:
        row = self._fetch_plan_row(plan_id, owner_id)
        if row is None:
            return None
        return TripPlan.model_validate_json(row["plan_json"])

    def get_request(self, plan_id: str, owner_id: str) -> TripPlanRequest | None:
        row = self._fetch_plan_row(plan_id, owner_id)
        if row is None:
            return None
        return TripPlanRequest.model_validate_json(row["request_json"])

    def delete_plan(self, plan_id: str, owner_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM trip_plans WHERE id = ? AND owner_id = ?",
                (plan_id, owner_id),
            )
        return bool(cursor.rowcount)

    def list_plans(self, owner_id: str, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, city, start_date, end_date, days, created_at, updated_at
                FROM trip_plans
                WHERE owner_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (owner_id, safe_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_feedback(self, plan_id: str, owner_id: str, feedback: PlanFeedback) -> str:
        """Record one "this stop is wrong" note; returns its id.

        Append-only and keyed by plan: the note is a signal about the planner, so it
        must survive the plan being edited afterwards.
        """
        feedback_id = uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO plan_feedback (
                    id, plan_id, owner_id, day_index, target, target_name,
                    reason, note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    plan_id,
                    owner_id,
                    feedback.day_index,
                    feedback.target,
                    feedback.target_name,
                    feedback.reason,
                    feedback.note,
                    self._now(),
                ),
            )
        return feedback_id

    def feedback_summary(self) -> list[dict[str, Any]]:
        """Counts by reason and target, newest data first. Across every owner."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT reason, target, COUNT(*) AS count
                FROM plan_feedback
                GROUP BY reason, target
                ORDER BY count DESC, reason
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def feedback_notes(self, limit: int = 20) -> list[dict[str, Any]]:
        """Recent free-text notes, with the plan's city, for reading by hand."""
        safe_limit = max(1, min(limit, 200))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT f.day_index, f.target_name, f.reason, f.note, f.created_at,
                       p.city, f.plan_id
                FROM plan_feedback f
                LEFT JOIN trip_plans p ON p.id = f.plan_id
                WHERE f.note IS NOT NULL AND f.note <> ''
                ORDER BY f.created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _fetch_plan_row(self, plan_id: str, owner_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT plan_json, request_json FROM trip_plans WHERE id = ? AND owner_id = ?",
                (plan_id, owner_id),
            ).fetchone()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """One short-lived connection: committed on success, always closed.

        ``sqlite3.Connection`` as a context manager commits the transaction but
        does **not** close the handle, so ``with sqlite3.connect(...)`` (the old
        shape here) leaked one connection and one file descriptor per call. On a
        long-running local server that eventually exhausts the process's handles.
        """
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:  # commit on success, roll back on exception
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _resolve_database_path(value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parents[2] / path

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
