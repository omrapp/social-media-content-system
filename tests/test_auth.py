"""
Auth security tests:
- Dev bypass only when BOTH secrets missing
- 401 returned when credentials missing
- Token expiry correctly rejected
"""
import pytest
from unittest.mock import patch
import jwt
import time


def test_dev_bypass_active_when_no_secrets(client):
    """With no JWT secret and no Supabase URL, any token passes (dev mode)."""
    with patch("backend.api.auth.SUPABASE_JWT_SECRET", ""), \
         patch("backend.api.auth.SUPABASE_URL", ""):
        resp = client.get(
            "/api/pipeline/runs",
            headers={"Authorization": "Bearer anything"},
        )
    assert resp.status_code == 200


def test_missing_auth_header_returns_403():
    """No Authorization header → 403 (HTTPBearer raises before verify_token)."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    with TestClient(app) as c:
        resp = c.get("/api/pipeline/runs")
    assert resp.status_code in (401, 403)


def test_expired_token_rejected():
    """Expired HS256 JWT must return 401."""
    secret = "test-secret-key-minimum-32-bytes!!"
    expired_token = jwt.encode(
        {"sub": "user1", "role": "authenticated", "exp": int(time.time()) - 3600, "aud": "authenticated"},
        secret,
        algorithm="HS256",
    )
    from fastapi.testclient import TestClient
    from backend.api.main import app
    with patch("backend.api.auth.SUPABASE_JWT_SECRET", secret), \
         patch("backend.api.auth.SUPABASE_URL", ""):
        with TestClient(app) as c:
            resp = c.get(
                "/api/pipeline/runs",
                headers={"Authorization": f"Bearer {expired_token}"},
            )
    assert resp.status_code == 401
    assert "expired" in resp.json().get("detail", "").lower()


def test_invalid_token_rejected():
    """Garbage token must return 401."""
    secret = "test-secret-key-minimum-32-bytes!!"
    from fastapi.testclient import TestClient
    from backend.api.main import app
    with patch("backend.api.auth.SUPABASE_JWT_SECRET", secret), \
         patch("backend.api.auth.SUPABASE_URL", ""):
        with TestClient(app) as c:
            resp = c.get(
                "/api/pipeline/runs",
                headers={"Authorization": "Bearer not.a.valid.jwt.token"},
            )
    assert resp.status_code == 401


def test_valid_hs256_token_accepted():
    """Valid HS256 JWT with correct audience passes."""
    secret = "test-secret-key-minimum-32-bytes!!"
    token = jwt.encode(
        {"sub": "user1", "role": "authenticated", "exp": int(time.time()) + 3600, "aud": "authenticated"},
        secret,
        algorithm="HS256",
    )
    from fastapi.testclient import TestClient
    from backend.api.main import app
    with patch("backend.api.auth.SUPABASE_JWT_SECRET", secret), \
         patch("backend.api.auth.SUPABASE_URL", ""):
        with TestClient(app) as c:
            resp = c.get(
                "/api/pipeline/runs",
                headers={"Authorization": f"Bearer {token}"},
            )
    assert resp.status_code == 200


def test_dev_bypass_disabled_when_secret_set():
    """Once SUPABASE_JWT_SECRET is set, dev bypass must NOT work with garbage token."""
    secret = "real-secret-key-minimum-32-bytes!!!"
    from fastapi.testclient import TestClient
    from backend.api.main import app
    with patch("backend.api.auth.SUPABASE_JWT_SECRET", secret), \
         patch("backend.api.auth.SUPABASE_URL", ""):
        with TestClient(app) as c:
            resp = c.get(
                "/api/pipeline/runs",
                headers={"Authorization": "Bearer garbage-token"},
            )
    assert resp.status_code == 401
