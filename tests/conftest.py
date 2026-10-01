import os
import pytest
from unittest.mock import patch, MagicMock


def pytest_addoption(parser):
    """--update-golden: rewrite the merge_clips golden fixtures instead of
    asserting against them. Equivalent to MERGE_GOLDEN=capture, which also works
    when this conftest isn't an initial conftest (bare `pytest` from the root).
    See tests/README_merge_golden.md."""
    parser.addoption(
        "--update-golden", action="store_true", default=False,
        help="capture/overwrite tests/fixtures/merge_golden/* instead of asserting",
    )


# Patch env vars before app import so auth doesn't require real Supabase
@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "")
    monkeypatch.setenv("SUPABASE_KEY", "")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "")
    monkeypatch.setenv("IG_TOKEN", "test_ig_token")
    monkeypatch.setenv("IG_USER_ID", "123456")


@pytest.fixture(autouse=True)
def mock_daemon(monkeypatch):
    """Prevent AsyncIOScheduler from starting during tests.

    AsyncIOScheduler leaves pending asyncio tasks that cause a SIGSEGV when
    the TestClient closes the event loop during teardown. Tests don't need
    the real scheduler — they exercise API routes, not background jobs.
    """
    monkeypatch.setattr("backend.pipeline.daemon.start", lambda: None)
    monkeypatch.setattr("backend.pipeline.daemon.stop", lambda: None)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def auth_headers():
    """Returns headers that bypass auth (dev mode: no JWT secret set)."""
    return {"Authorization": "Bearer dev-bypass-token"}
