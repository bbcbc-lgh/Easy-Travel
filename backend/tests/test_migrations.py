"""Schema migrations.

The interesting case is the one the old inline DDL handled without any test: a
database created before owner_id existed, which must be carried forward in place
rather than recreated.
"""

import sqlite3
from pathlib import Path

from src.service.migrations import (
    MIGRATIONS,
    applied_versions,
    pending_versions,
    run_migrations,
)

LEGACY_SCHEMA = """
    CREATE TABLE trip_plans (
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


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def test_fresh_database_gets_every_migration(tmp_path: Path) -> None:
    connection = connect(tmp_path / "fresh.sqlite3")

    applied = run_migrations(connection)

    assert applied == [migration.name for migration in MIGRATIONS]
    assert applied_versions(connection) == {migration.version for migration in MIGRATIONS}
    assert pending_versions(connection) == []
    connection.close()


def test_running_twice_applies_nothing(tmp_path: Path) -> None:
    connection = connect(tmp_path / "twice.sqlite3")
    run_migrations(connection)

    assert run_migrations(connection) == []
    connection.close()


def test_legacy_table_without_owner_id_is_carried_forward(tmp_path: Path) -> None:
    """A database from before owner_id existed keeps its rows and gains the column."""
    connection = connect(tmp_path / "legacy.sqlite3")
    connection.execute(LEGACY_SCHEMA)
    connection.execute(
        """
        INSERT INTO trip_plans (id, city, start_date, end_date, days,
                                request_json, plan_json, created_at, updated_at)
        VALUES ('old', '杭州', '2026-11-20', '2026-11-21', 2, '{}', '{}', 'now', 'now')
        """
    )

    applied = run_migrations(connection)

    assert "add owner_id" in applied
    row = connection.execute("SELECT owner_id FROM trip_plans WHERE id = 'old'").fetchone()
    assert row["owner_id"] == "legacy"
    connection.close()


def test_partial_history_only_applies_the_remainder(tmp_path: Path) -> None:
    """Every migration but the last already ran; only the last may apply."""
    done, last = MIGRATIONS[:-1], MIGRATIONS[-1]
    connection = connect(tmp_path / "partial.sqlite3")
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    for migration in done:
        connection.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (migration.version, migration.name),
        )
    # The schema as of the previous migration: trip_plans with owner_id.
    connection.execute(
        """
        CREATE TABLE trip_plans (
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

    applied = run_migrations(connection)

    assert applied == [last.name]
    assert pending_versions(connection) == []
    connection.close()


def test_applied_versions_is_empty_before_the_table_exists(tmp_path: Path) -> None:
    connection = connect(tmp_path / "empty.sqlite3")

    assert applied_versions(connection) == set()
    assert pending_versions(connection) == [migration.version for migration in MIGRATIONS]
    connection.close()
