"""
Tests for settings API:
- GET /api/settings — returns all groups + secrets_set booleans
- GET /api/settings/{group} — known group returns value, unknown returns 404
- PUT /api/settings — partial merge, secret write rejected
- All new DEFAULTS groups present: taxonomy, analytics, pipeline, video
- Secrets-set map contains expected keys as booleans
"""
import pytest
from unittest.mock import patch


ALL_GROUPS = [
    "approval", "schedule", "ai", "telegram", "music",
    "taxonomy", "platforms", "analytics", "pipeline", "branding",
]

SECRET_KEYS = [
    "telegram.bot_token",
    "ai.groq_api_key",
    "ai.openrouter_api_key",
    "platforms.youtube_client_secret",
    "platforms.youtube_refresh_token",
    "platforms.tiktok_client_secret",
    "platforms.tiktok_access_token",
]


def _get_settings(client, auth_headers):
    with patch("backend.api.routes.settings.get_all_settings", return_value={}):
        return client.get("/api/settings", headers=auth_headers)


# ── GET /api/settings ──────────────────────────────────────────────────────────

def test_get_settings_returns_200(client, auth_headers):
    resp = _get_settings(client, auth_headers)
    assert resp.status_code == 200


def test_get_settings_shape(client, auth_headers):
    resp = _get_settings(client, auth_headers)
    data = resp.json()
    assert "settings" in data
    assert "secrets_set" in data


def test_get_settings_all_groups_present(client, auth_headers):
    resp = _get_settings(client, auth_headers)
    settings = resp.json()["settings"]
    for group in ALL_GROUPS:
        assert group in settings, f"Missing group: {group}"


def test_secrets_set_contains_expected_keys(client, auth_headers):
    resp = _get_settings(client, auth_headers)
    secrets_set = resp.json()["secrets_set"]
    for key in SECRET_KEYS:
        assert key in secrets_set, f"Missing secret key: {key}"


def test_secrets_set_values_are_booleans(client, auth_headers):
    resp = _get_settings(client, auth_headers)
    secrets_set = resp.json()["secrets_set"]
    for k, v in secrets_set.items():
        assert isinstance(v, bool), f"secrets_set.{k} should be bool, got {type(v)}"


def test_settings_defaults_are_lazy_filled(client, auth_headers):
    """Empty DB → DEFAULTS fill in all groups."""
    with patch("backend.db.get_all_settings", return_value={}):
        resp = client.get("/api/settings", headers=auth_headers)
    settings = resp.json()["settings"]
    # taxonomy group has the categories list
    assert "categories" in settings["taxonomy"]
    # pipeline group has stages_enabled
    assert "stages_enabled" in settings["pipeline"]


# ── GET /api/settings/{group} ─────────────────────────────────────────────────

def test_get_known_group_200(client, auth_headers):
    with patch("backend.db.get_setting", return_value={"categories": ["food", "culture"]}):
        resp = client.get("/api/settings/taxonomy", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["group"] == "taxonomy"
    assert "value" in data


def test_get_unknown_group_404(client, auth_headers):
    resp = client.get("/api/settings/nonexistent_group", headers=auth_headers)
    assert resp.status_code == 404
    assert "Unknown settings group" in resp.json().get("detail", "")


# ── PUT /api/settings ─────────────────────────────────────────────────────────

def test_put_known_group_merges(client, auth_headers):
    current = {"categories": ["food", "culture"], "require_video_only": True}
    with patch("backend.api.routes.settings.get_setting", return_value=current), \
         patch("backend.api.routes.settings.set_setting") as mock_ss:
        resp = client.put(
            "/api/settings",
            json={"group": "taxonomy", "value": {"categories": ["food"]}},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["value"]["categories"] == ["food"]
    assert data["value"]["require_video_only"] is True  # untouched fields preserved
    mock_ss.assert_called_once()


def test_put_unknown_group_400(client, auth_headers):
    resp = client.put(
        "/api/settings",
        json={"group": "fake_group", "value": {"foo": "bar"}},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "Unknown settings group" in resp.json().get("detail", "")


def test_put_secret_key_rejected(client, auth_headers):
    """Attempting to write a secret key via the API must return 400."""
    resp = client.put(
        "/api/settings",
        json={"group": "telegram", "value": {"bot_token": "REAL_SECRET_VALUE"}},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "env-only" in resp.json().get("detail", "").lower() or \
           "bot_token" in resp.json().get("detail", "")


# ── New groups structural checks ──────────────────────────────────────────────

def test_taxonomy_defaults_structure(client, auth_headers):
    resp = _get_settings(client, auth_headers)
    taxonomy = resp.json()["settings"]["taxonomy"]
    assert isinstance(taxonomy["categories"], list)
    assert len(taxonomy["categories"]) > 0


def test_pipeline_defaults_structure(client, auth_headers):
    resp = _get_settings(client, auth_headers)
    pipeline = resp.json()["settings"]["pipeline"]
    assert "stages_enabled" in pipeline
    stages = pipeline["stages_enabled"]
    for stage in ("index", "classify", "resize", "edit", "caption", "upload"):
        assert stage in stages, f"stages_enabled missing: {stage}"


def test_analytics_defaults_structure(client, auth_headers):
    resp = _get_settings(client, auth_headers)
    analytics = resp.json()["settings"]["analytics"]
    assert "ingest_interval_hours" in analytics
    assert isinstance(analytics["ingest_interval_hours"], int)


def test_platforms_defaults_include_enabled_flags(client, auth_headers):
    """DEFAULTS include all platform enabled flags — verify keys exist in the defaults dict."""
    from backend.api.routes.settings import DEFAULTS
    platforms = DEFAULTS["platforms"]
    assert "instagram_enabled" in platforms
    assert "youtube_enabled" in platforms
    assert "tiktok_enabled" in platforms
