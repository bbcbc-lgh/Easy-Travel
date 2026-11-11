import contextlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.config import Settings
from src.model.schemas import TripPlan, TripPlanRequest

LEGACY_OWNER = "legacy"


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
                    owner_id TEXT NOT NULL DEFAULT 'legacy',
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
            self._migrate_owner_column(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trip_plans_owner_created_at
                ON trip_plans(owner_id, created_at DESC)
                """
            )

    @staticmethod
    def _migrate_owner_column(connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(trip_plans)")}
        if "owner_id" not in columns:
            connection.execute(f"ALTER TABLE trip_plans ADD COLUMN owner_id TEXT NOT NULL DEFAULT '{LEGACY_OWNER}'")

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
