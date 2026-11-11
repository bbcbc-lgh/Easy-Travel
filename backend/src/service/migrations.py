"""Versioned schema migrations for the SQLite store.

The repository talks to sqlite3 directly rather than through an ORM, so Alembic
(which assumes SQLAlchemy models and a URL) would be a large dependency for a
single table. This is the smallest thing that still behaves:

* migrations are an ordered, named list;
* one transaction per migration, together with its version row;
* every migration is written idempotently, so an existing database that predates
  the runner is simply carried forward instead of needing a baseline script.
"""

import logging
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from src.service.logging import log_event

logger = logging.getLogger(__name__)

# Spelled out in each statement rather than interpolated: a table name cannot be a
# bound parameter, and f-strings here trip S608 (SQL injection) on a constant.
_CREATE_VERSION_TABLE = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """
_SELECT_VERSIONS = "SELECT version FROM schema_migrations"
_INSERT_VERSION = "INSERT INTO schema_migrations (version, name) VALUES (?, ?)"


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _create_trip_plans(connection: sqlite3.Connection) -> None:
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


def _add_owner_column(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(trip_plans)")}
    if "owner_id" not in columns:
        connection.execute("ALTER TABLE trip_plans ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'legacy'")


def _index_owner_and_created_at(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_trip_plans_owner_created_at
        ON trip_plans(owner_id, created_at DESC)
        """
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "create trip_plans", _create_trip_plans),
    Migration(2, "add owner_id", _add_owner_column),
    Migration(3, "index owner_id + created_at", _index_owner_and_created_at),
)


def applied_versions(connection: sqlite3.Connection) -> set[int]:
    """Versions already recorded. An unreadable table means "nothing applied"."""
    try:
        rows = connection.execute(_SELECT_VERSIONS).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {row["version"] for row in rows}


def run_migrations(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> list[str]:
    """Apply pending migrations in order; return the names applied this run."""
    connection.execute(_CREATE_VERSION_TABLE)
    already = applied_versions(connection)
    applied: list[str] = []
    for migration in sorted(migrations, key=lambda item: item.version):
        if migration.version in already:
            continue
        migration.apply(connection)
        connection.execute(
            _INSERT_VERSION,
            (migration.version, migration.name),
        )
        applied.append(migration.name)
        log_event(
            logger,
            "db.migration_applied",
            version=migration.version,
            name=migration.name,
        )
    return applied


def pending_versions(connection: sqlite3.Connection, migrations: Iterable[Migration] = MIGRATIONS) -> list[int]:
    """Versions the store still needs. Handy for a health check or a test assertion."""
    already = applied_versions(connection)
    return [migration.version for migration in migrations if migration.version not in already]
