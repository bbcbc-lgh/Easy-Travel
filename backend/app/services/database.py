import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.models.schemas import TripPlan, TripPlanRequest


class TripPlanRepository:
    def __init__(self, settings: Settings):
        self.database_path = self._resolve_database_path(settings.database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trip_plans (
                    id TEXT PRIMARY KEY,
                    city TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    days INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trip_plans_created_at
                ON trip_plans(created_at DESC)
                """
            )

    def save_plan(self, request: TripPlanRequest, plan: TripPlan) -> TripPlan:
        plan_id = plan.id or uuid4().hex
        now = self._now()
        plan.id = plan_id
        payload = plan.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO trip_plans (
                    id, city, start_date, end_date, days,
                    request_json, plan_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def update_plan(self, plan_id: str, plan: TripPlan) -> TripPlan | None:
        existing = self.get_plan(plan_id)
        if existing is None:
            return None
        plan.id = plan_id
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE trip_plans
                SET city = ?, start_date = ?, end_date = ?, days = ?,
                    plan_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    plan.city,
                    plan.start_date,
                    plan.end_date,
                    len(plan.days),
                    plan.model_dump_json(),
                    now,
                    plan_id,
                ),
            )
        return plan if cursor.rowcount else None

    def get_plan(self, plan_id: str) -> TripPlan | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT plan_json FROM trip_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return TripPlan.model_validate_json(row["plan_json"])

    def list_plans(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, city, start_date, end_date, days, created_at, updated_at
                FROM trip_plans
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _resolve_database_path(value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parents[2] / path

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
