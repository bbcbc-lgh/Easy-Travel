"""Repository behaviour that the HTTP tests cannot see: handle hygiene and schema.

``sqlite3.Connection`` used as a context manager commits but never closes. The
repository used that shape, so every call leaked one connection; a long-running
local server would eventually run out of handles. These tests fail if the
``_connect`` helper ever stops closing.
"""

import sqlite3
from datetime import date

import pytest

from src.config import Settings
from src.model.schemas import DayPlan, TripPlan, TripPlanRequest
from src.service import database as database_module
from src.service.database import TripPlanRepository


@pytest.fixture
def opened_connections(tmp_path, monkeypatch):
    """Track every connection the repository opens."""
    opened: list[sqlite3.Connection] = []
    real_connect = database_module.sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(database_module.sqlite3, "connect", tracking_connect)
    return opened


def _is_closed(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("select 1")
    except sqlite3.ProgrammingError:
        return True
    return False


def _request() -> TripPlanRequest:
    return TripPlanRequest(
        city="杭州",
        start_date=date(2026, 11, 20),
        days=1,
        preferences="历史文化",
        budget="中等",
        transportation="公共交通",
        accommodation="经济型酒店",
    )


def _plan() -> TripPlan:
    return TripPlan(
        city="杭州",
        start_date="2026-11-20",
        end_date="2026-11-20",
        days=[
            DayPlan(
                date="2026-11-20",
                day_index=0,
                description="城市漫步",
                transportation="公共交通",
                accommodation="经济型酒店",
            )
        ],
        overall_suggestions="出发前确认开放时间。",
    )


def test_every_operation_closes_its_connection(tmp_path, opened_connections) -> None:
    repository = TripPlanRepository(Settings(database_path=str(tmp_path / "owns.sqlite3")))

    saved = repository.save_plan(_request(), _plan(), "owner-a")
    assert repository.get_plan(saved.id, "owner-a") is not None
    assert repository.get_request(saved.id, "owner-a") is not None
    assert len(repository.list_plans("owner-a")) == 1
    assert repository.delete_plan(saved.id, "owner-a") is True

    assert opened_connections, "expected the repository to open connections"
    leaked = [connection for connection in opened_connections if not _is_closed(connection)]
    assert not leaked, f"{len(leaked)} of {len(opened_connections)} connections were never closed"


def test_repeated_reads_do_not_accumulate_open_handles(tmp_path, opened_connections) -> None:
    """A poll loop (history page, dashboard) must not grow the handle count."""
    repository = TripPlanRepository(Settings(database_path=str(tmp_path / "poll.sqlite3")))

    for _ in range(25):
        repository.list_plans("owner-a")

    assert len(opened_connections) >= 25
    assert all(_is_closed(connection) for connection in opened_connections)


def test_schema_creation_is_idempotent(tmp_path) -> None:
    path = str(tmp_path / "again.sqlite3")
    first = TripPlanRepository(Settings(database_path=path))
    first.save_plan(_request(), _plan(), "owner-a")

    reopened = TripPlanRepository(Settings(database_path=path))

    assert len(reopened.list_plans("owner-a")) == 1
