"""
Tests for pipeline route ordering fix.
Critical: /orchestrate and /full must NOT be caught by /{stage} wildcard.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


def test_orchestrate_not_caught_by_stage_wildcard(client, auth_headers):
    """
    Regression: /{stage} was defined before /orchestrate, causing 400 "Unknown stage: orchestrate".
    /orchestrate must resolve to trigger_orchestrator, not trigger_stage.
    """
    mock_result = {"stages_run": [], "errors": []}
    with patch("backend.pipeline.orchestrator.run", return_value=mock_result):
        resp = client.post(
            "/api/pipeline/orchestrate",
            json={"stages": None, "include_downloads": False},
            headers=auth_headers,
        )
    # Must NOT be 400 "Unknown stage: orchestrate"
    assert resp.status_code != 400, f"Route ordering bug: {resp.json()}"
    assert resp.status_code == 200


def test_full_not_caught_by_stage_wildcard(client, auth_headers):
    """
    /full must resolve to trigger_full, not trigger_stage.
    """
    with patch("backend.api.routes.pipeline._run_stage", return_value={"ok": True}):
        resp = client.post(
            "/api/pipeline/full",
            json={},
            headers=auth_headers,
        )
    assert resp.status_code != 400 or "Unknown stage" not in resp.text


def test_unknown_stage_returns_400(client, auth_headers):
    """Valid stages pass; garbage stage returns 400."""
    resp = client.post(
        "/api/pipeline/nonexistent_stage_xyz",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "Unknown stage" in resp.json().get("detail", "")


def test_valid_stage_index_dispatches(client, auth_headers):
    mock_result = {"indexed": 0, "skipped": 0}
    with patch("backend.pipeline.index_content.run", return_value=mock_result):
        resp = client.post(
            "/api/pipeline/index",
            json={},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "index"


def test_pipeline_runs_endpoint(client, auth_headers):
    """GET /runs returns list (empty when Supabase not configured)."""
    resp = client.get("/api/pipeline/runs", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
