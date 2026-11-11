import uuid

import pytest
from fastapi.testclient import TestClient

from src.api.deps import get_generation_guard, get_pipeline, get_trip_plan_repository
from src.api.main import app
from src.config import settings


class OwnedClient(TestClient):
    """TestClient that always presents an anonymous owner id."""

    def __init__(self, client_id: str | None = None, **kwargs) -> None:
        super().__init__(app, **kwargs)
        self.client_id = client_id or uuid.uuid4().hex[:16]

    def request(self, *args, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("X-Client-Id", self.client_id)
        return super().request(*args, headers=headers, **kwargs)

    def stream(self, *args, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        headers.setdefault("X-Client-Id", self.client_id)
        return super().stream(*args, headers=headers, **kwargs)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Every test gets its own SQLite file; the dev database is never touched."""
    database = tmp_path / "test.sqlite3"
    monkeypatch.setattr(settings, "database_path", str(database))
    get_trip_plan_repository.cache_clear()
    get_pipeline.cache_clear()
    get_generation_guard.cache_clear()
    yield database
    get_trip_plan_repository.cache_clear()
    get_pipeline.cache_clear()
    get_generation_guard.cache_clear()


@pytest.fixture
def offline_mode(monkeypatch):
    """Force sample data so tests never touch the network or a paid API."""
    monkeypatch.setattr(settings, "use_sample_data", True)
    get_pipeline.cache_clear()
    yield
    get_pipeline.cache_clear()


@pytest.fixture
def owned_client() -> OwnedClient:
    return OwnedClient()


@pytest.fixture
def other_client() -> OwnedClient:
    return OwnedClient()


def trip_request(**overrides) -> dict:
    payload = {
        "city": "杭州",
        "start_date": "2026-11-20",
        "days": 2,
        "preferences": "历史文化",
        "budget": "中等",
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def plan_payload():
    return trip_request
