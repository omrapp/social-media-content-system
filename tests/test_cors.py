"""
CORS tests: production origins must be allowed, non-listed origins must be blocked.
"""
import os

import pytest
from fastapi.testclient import TestClient

# _CORS_ORIGINS is built at import time, so set the env before main is imported.
os.environ.setdefault("CORS_ORIGINS", "https://app.example.com,https://www.app.example.com")


ALLOWED_ORIGINS = [
    "https://app.example.com",
    "https://www.app.example.com",
    "http://localhost:5173",
    "http://localhost:3000",
]

BLOCKED_ORIGINS = [
    "https://evil.com",
    "https://app.example.com.evil.com",
    "http://app.example.com",  # http not https in prod
]


@pytest.mark.parametrize("origin", ALLOWED_ORIGINS)
def test_cors_allowed_origins(origin):
    from backend.api.main import app
    with TestClient(app) as c:
        resp = c.options(
            "/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.headers.get("access-control-allow-origin") == origin, \
        f"Origin {origin} should be allowed"


@pytest.mark.parametrize("origin", BLOCKED_ORIGINS)
def test_cors_blocked_origins(origin):
    from backend.api.main import app
    with TestClient(app) as c:
        resp = c.options(
            "/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao != origin, f"Origin {origin} should NOT be allowed, got: {acao}"


def test_vercel_preview_allowed():
    """Vercel preview URLs match allow_origin_regex.

    The regex is tightened to the configured VERCEL_PROJECT_SLUG when set, so
    derive a matching preview origin from the same env var the app reads (falls
    back to the broad *.vercel.app pattern when no slug is configured).
    """
    import os
    from backend.api.main import app
    slug = os.environ.get("VERCEL_PROJECT_SLUG", "")
    origin = (
        f"https://{slug}-git-preview-branch.vercel.app"
        if slug
        else "https://my-app-abc123.vercel.app"
    )
    with TestClient(app) as c:
        resp = c.options(
            "/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
    acao = resp.headers.get("access-control-allow-origin", "")
    assert acao == origin, f"Vercel preview {origin} should be allowed"
