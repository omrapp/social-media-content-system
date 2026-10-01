"""
Tests for backend.pipeline.trends_fetcher

Covers:
- fetch_trends() always runs ungeo-targeted (global), no country param
- Cache key is a date string; same-day calls hit the cache
- trends_block() renders the fetched trends into a prompt fragment
- Graceful degradation when pytrends unavailable or the request fails
"""
import pytest
from datetime import date
from unittest.mock import patch, MagicMock


# ── Cache key structure ───────────────────────────────────────────────────────

def test_cache_key_is_date_string():
    """The cache key must be today's ISO date string."""
    from backend.pipeline import trends_fetcher

    trends_fetcher._cache.clear()

    mock_pt = MagicMock()
    mock_pt.related_queries.return_value = {}
    mock_pytrends_module = MagicMock()
    mock_pytrends_module.request.TrendReq.return_value = mock_pt

    with patch.dict("sys.modules", {
        "pytrends": mock_pytrends_module,
        "pytrends.request": mock_pytrends_module.request,
    }):
        trends_fetcher.fetch_trends()

    today = date.today().isoformat()
    assert today in trends_fetcher._cache


def test_same_day_uses_cache():
    """Second call on the same day should hit cache (pytrends called only once)."""
    from backend.pipeline import trends_fetcher

    trends_fetcher._cache.clear()

    mock_pt = MagicMock()
    mock_pt.related_queries.return_value = {}
    mock_pytrends_module = MagicMock()
    mock_pytrends_module.request.TrendReq.return_value = mock_pt

    with patch.dict("sys.modules", {
        "pytrends": mock_pytrends_module,
        "pytrends.request": mock_pytrends_module.request,
    }):
        trends_fetcher.fetch_trends()
        trends_fetcher.fetch_trends()  # second call

    # TrendReq should only be constructed once (cache hit on second call).
    assert mock_pytrends_module.request.TrendReq.call_count == 1


def test_fetch_trends_respects_limit():
    from backend.pipeline import trends_fetcher

    trends_fetcher._cache.clear()
    trends_fetcher._cache[date.today().isoformat()] = ["a", "b", "c", "d"]
    assert trends_fetcher.fetch_trends(limit=2) == ["a", "b"]


# ── trends_block ──────────────────────────────────────────────────────────────

def test_trends_block_empty_returns_empty_string():
    from backend.pipeline import trends_fetcher

    with patch.object(trends_fetcher, "fetch_trends", return_value=[]):
        result = trends_fetcher.trends_block()
    assert result == ""


def test_trends_block_with_results_returns_nonempty():
    from backend.pipeline import trends_fetcher

    with patch.object(trends_fetcher, "fetch_trends", return_value=["cherry blossom", "onsen"]):
        result = trends_fetcher.trends_block()
    assert "cherry blossom" in result
    assert "onsen" in result


# ── Graceful degradation ──────────────────────────────────────────────────────

def test_fetch_returns_empty_list_when_pytrends_missing():
    """If pytrends is not installed, fetch must return [] without raising."""
    from backend.pipeline import trends_fetcher

    trends_fetcher._cache.clear()

    with patch.dict("sys.modules", {"pytrends": None, "pytrends.request": None}):
        result = trends_fetcher.fetch_trends()
    assert result == []


def test_fetch_returns_empty_list_when_request_fails():
    """Network failure in pytrends must degrade to [] without raising."""
    from backend.pipeline import trends_fetcher

    trends_fetcher._cache.clear()

    mock_pt = MagicMock()
    mock_pt.related_queries.side_effect = RuntimeError("HTTP 429 rate limited")
    mock_pytrends_module = MagicMock()
    mock_pytrends_module.request.TrendReq.return_value = mock_pt

    with patch.dict("sys.modules", {
        "pytrends": mock_pytrends_module,
        "pytrends.request": mock_pytrends_module.request,
    }):
        result = trends_fetcher.fetch_trends()
    assert result == []
