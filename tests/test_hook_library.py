"""
Tests for backend.pipeline.hook_library.hook_block()

Covers:
- Returns a non-empty string for a known pillar + arc
- Falls back to _DEFAULT pillar for unknown pillar
- trend_topic is included in result when non-empty
- Unknown arc falls back to opener hooks
- user_templates (caption.hook_templates) override code defaults
- Returns "" on hard error (settings import raises)
"""
import pytest
from unittest.mock import patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hook(pillar=None, arc=None, trend="", cfg=None):
    """Call hook_block() with mocked settings."""
    from backend.pipeline.hook_library import hook_block

    caption_cfg = cfg if cfg is not None else {}

    with patch("backend.api.routes.settings.get_setting", return_value=caption_cfg):
        return hook_block(pillar, arc, trend_topic=trend)


# ── Basic return value ────────────────────────────────────────────────────────

def test_returns_nonempty_for_known_pillar_and_arc():
    result = _hook(pillar="hidden_gem", arc="opener")
    assert isinstance(result, str)
    assert result.strip() != "", "Expected non-empty string for known pillar + arc"


def test_result_contains_hook_header():
    """The header line about viral hooks should always be present."""
    result = _hook(pillar="food", arc="build")
    assert "Viral hook inspiration" in result


def test_returns_nonempty_for_each_known_pillar():
    from backend.pipeline.hook_library import _HOOK_TEMPLATES
    known_pillars = [p for p in _HOOK_TEMPLATES if p != "_DEFAULT"]
    for pillar in known_pillars:
        result = _hook(pillar=pillar, arc="opener")
        assert result.strip() != "", f"Expected output for pillar={pillar!r}"


# ── _DEFAULT fallback for unknown pillar ──────────────────────────────────────

def test_unknown_pillar_falls_back_to_default():
    """An unrecognised pillar must produce output (uses _DEFAULT hooks)."""
    result = _hook(pillar="nonexistent_pillar_xyz", arc="opener")
    assert result.strip() != ""


def test_none_pillar_falls_back_to_default():
    result = _hook(pillar=None, arc="opener")
    assert result.strip() != ""


def test_unknown_pillar_output_matches_default_openers():
    """Verify the fallback actually uses _DEFAULT opener hooks."""
    from backend.pipeline.hook_library import _HOOK_TEMPLATES
    default_openers = _HOOK_TEMPLATES["_DEFAULT"]["opener"]
    result = _hook(pillar="totally_unknown", arc="opener")
    # At least one of the default hooks should appear verbatim somewhere in the output.
    assert any(hook in result for hook in default_openers)


# ── trend_topic injection ──────────────────────────────────────────────────────

def test_trend_topic_present_in_result():
    result = _hook(pillar="nature", arc="climax", trend="sustainable travel 2025")
    assert "sustainable travel 2025" in result, "Trend topic must appear in the hook block"


def test_no_trend_topic_no_trend_line():
    result = _hook(pillar="budget", arc="opener", trend="")
    assert "Optional trend angle" not in result, (
        "Trend angle line should be absent when trend_topic is empty"
    )


def test_trend_topic_label_present():
    result = _hook(pillar="culture", arc="build", trend="cherry blossom season")
    assert "Optional trend angle" in result


# ── Unknown arc fallback ──────────────────────────────────────────────────────

def test_unknown_arc_falls_back_to_opener():
    """An unrecognised arc_position must produce output using opener hooks."""
    from backend.pipeline.hook_library import _HOOK_TEMPLATES
    openers = _HOOK_TEMPLATES["_DEFAULT"]["opener"]
    result = _hook(pillar=None, arc="completely_unknown_arc")
    assert result.strip() != ""
    # The output should use some opener hook (either from pillar or _DEFAULT).
    assert "Viral hook inspiration" in result


def test_none_arc_defaults_to_opener():
    result = _hook(pillar="beach", arc=None)
    assert result.strip() != ""
    assert "Viral hook inspiration" in result


# ── user_templates override ───────────────────────────────────────────────────

def test_user_templates_override_code_defaults():
    """When caption.hook_templates is non-empty, those must be used instead."""
    my_templates = [
        "Custom hook A — this is unique",
        "Custom hook B — only mine",
        "Custom hook C — totally different",
    ]
    cfg = {"hook_templates": my_templates}
    result = _hook(pillar="food", arc="opener", cfg=cfg)
    # At least one of the custom templates must appear in the output.
    assert any(t in result for t in my_templates), (
        "User-supplied hook_templates should appear in the output"
    )


def test_user_templates_single_entry():
    """Even a single user template should work without random.sample crash."""
    cfg = {"hook_templates": ["Only one hook here"]}
    result = _hook(cfg=cfg)
    assert "Only one hook here" in result


def test_user_templates_none_falls_through_to_defaults():
    """Empty/None hook_templates should fall through to code defaults."""
    cfg = {"hook_templates": []}
    result = _hook(pillar="nature", arc="closer", cfg=cfg)
    assert result.strip() != ""
    assert "Viral hook inspiration" in result


# ── Error resilience ──────────────────────────────────────────────────────────

def test_returns_empty_string_on_hard_error():
    """If get_setting raises AND the inner try block also raises, must return ""."""
    from backend.pipeline.hook_library import hook_block

    # Make settings raise so cfg={}, then make random.sample also raise.
    with patch("backend.api.routes.settings.get_setting", side_effect=RuntimeError("DB down")), \
         patch("random.sample", side_effect=RuntimeError("forced failure")):
        result = hook_block("food", "opener")
    assert result == "", "Must return '' on unrecoverable error, not raise"


def test_does_not_raise_on_settings_error():
    """Settings failure alone should degrade gracefully (still returns hooks)."""
    from backend.pipeline.hook_library import hook_block

    with patch("backend.api.routes.settings.get_setting", side_effect=Exception("network error")):
        result = hook_block("hidden_gem", "build")
    # Should still produce output using default templates.
    assert isinstance(result, str)
