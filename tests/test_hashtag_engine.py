"""
Tests for backend.pipeline.hashtag_engine.blend()

Covers:
- Platform caps (ig≤30, tiktok≤5, youtube≤15)
- Curated tags mixed in first
- Rotation by post_seq
- Denylist filtering
- curated_enabled=False behaviour
- Unknown platform (no crash, uses _DEFAULT_CAP)
- Empty llm_tags (returns curated picks)
"""
import pytest
from unittest.mock import patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _blend(*args, settings=None, **kwargs):
    """Call blend() with mocked get_setting so no DB is needed."""
    from backend.pipeline.hashtag_engine import blend

    cfg = settings if settings is not None else {
        "curated_enabled": True,
        "blend_count": 8,
        "pools": {},           # empty → code uses _DEFAULT_POOLS
        "blocked": [],         # empty → defers to _DEFAULT_BLOCKED_TAGS from caption_gen
    }

    # get_setting is imported *inside* the function at runtime, so we patch
    # the source module where it lives.
    with patch("backend.api.routes.settings.get_setting", return_value=cfg):
        return blend(*args, **kwargs)


# ── Platform cap tests ─────────────────────────────────────────────────────────

def test_blend_cap_instagram():
    many_tags = [f"tag{i}" for i in range(50)]
    result = _blend(many_tags, "instagram")
    assert len(result) <= 5


def test_blend_cap_tiktok():
    many_tags = [f"tag{i}" for i in range(50)]
    result = _blend(many_tags, "tiktok")
    assert len(result) <= 5


def test_blend_cap_youtube():
    many_tags = [f"tag{i}" for i in range(50)]
    result = _blend(many_tags, "youtube")
    assert len(result) <= 5


# ── Curated-first ordering ─────────────────────────────────────────────────────

def test_curated_tags_appear_before_llm_tags():
    """User-configured pool entries must appear at the front of the result."""
    custom_pool = ["curatedA", "curatedB", "curatedC"]
    cfg = {
        "curated_enabled": True,
        "blend_count": 3,
        "pools": {"instagram": custom_pool},
        "blocked": [],
    }
    llm_tags = ["llmtag1", "llmtag2", "llmtag3"]
    result = _blend(llm_tags, "instagram", settings=cfg)

    # All curated picks should appear, and before any LLM tag.
    curated_indices = [result.index(t) for t in custom_pool if t in result]
    llm_indices = [result.index(t) for t in llm_tags if t in result]
    assert curated_indices, "No curated tags found in result"
    assert llm_indices, "No LLM tags found in result"
    assert max(curated_indices) < min(llm_indices), (
        "Curated tags must come before LLM tags in result"
    )


# ── Rotation by post_seq ───────────────────────────────────────────────────────

def test_rotation_by_post_seq_differs():
    """Different post_seq values should produce different curated picks."""
    pool = [f"poolTag{i}" for i in range(10)]
    cfg = {
        "curated_enabled": True,
        "blend_count": 3,
        "pools": {"instagram": pool},
        "blocked": [],
    }
    result_0 = _blend([], "instagram", post_seq=0, settings=cfg)
    result_1 = _blend([], "instagram", post_seq=1, settings=cfg)
    # Shifting the start index by 1 must change which curated tags are picked.
    assert result_0 != result_1, "Different post_seq should yield different curated tag selections"


def test_rotation_wraps_around():
    """post_seq that exceeds pool size should wrap and still return tags."""
    pool = ["alpha", "beta", "gamma"]
    cfg = {
        "curated_enabled": True,
        "blend_count": 3,
        "pools": {"instagram": pool},
        "blocked": [],
    }
    result = _blend([], "instagram", post_seq=999, settings=cfg)
    assert len(result) > 0, "Should still return curated tags when post_seq wraps"
    # All returned tags must come from the pool.
    for tag in result:
        assert tag in pool


# ── Denylist filtering ─────────────────────────────────────────────────────────

def test_default_blocked_tags_removed():
    """Default blocked tags (travel, instatravel, etc.) must be filtered out."""
    blocked_tags = ["travel", "instatravel", "photography", "instagood"]
    result = _blend(blocked_tags, "instagram")
    for tag in blocked_tags:
        assert tag not in result, f"Blocked tag '{tag}' should have been removed"


def test_custom_blocked_tags_removed():
    """Custom blocked list in settings takes effect."""
    cfg = {
        "curated_enabled": True,
        "blend_count": 3,
        "pools": {},
        "blocked": ["mytag", "anothertag"],
    }
    result = _blend(["mytag", "anothertag", "safetag"], "instagram", settings=cfg)
    assert "mytag" not in result
    assert "anothertag" not in result
    assert "safetag" in result


def test_hash_prefix_stripped_before_block_check():
    """Tags with leading '#' should be normalised and still checked against denylist."""
    blocked_tag_with_hash = ["#travel"]
    result = _blend(blocked_tag_with_hash, "instagram")
    assert "travel" not in result
    assert "#travel" not in result


# ── Deduplication ─────────────────────────────────────────────────────────────

def test_duplicates_removed():
    tags = ["uniquetag", "uniquetag", "UniqueTag", "#uniquetag"]
    # blend_count=2 leaves 3 slots for LLM tags within the 5-tag cap
    result = _blend(tags, "instagram", settings={
        "curated_enabled": True, "blend_count": 2,
        "pools": {}, "blocked": [],
    })
    lower_results = [t.lower() for t in result]
    assert lower_results.count("uniquetag") == 1, "Duplicate tags should be collapsed to one"


# ── curated_enabled=False ──────────────────────────────────────────────────────

def test_curated_disabled_returns_only_llm_tags():
    """When curated_enabled=False, result must be LLM tags only (deduped + capped)."""
    cfg = {
        "curated_enabled": False,
        "blend_count": 8,
        "pools": {"instagram": ["curatedTag1", "curatedTag2"]},
        "blocked": [],
    }
    llm_tags = ["llmA", "llmB", "llmC"]
    result = _blend(llm_tags, "instagram", settings=cfg)
    for tag in result:
        assert tag not in ["curatedTag1", "curatedTag2"], (
            "Curated tags must be absent when curated_enabled=False"
        )
    # LLM tags should be present.
    for tag in llm_tags:
        assert tag in result


def test_curated_disabled_still_applies_cap():
    cfg = {
        "curated_enabled": False,
        "blend_count": 8,
        "pools": {},
        "blocked": [],
    }
    many_tags = [f"llmtag{i}" for i in range(100)]
    result = _blend(many_tags, "tiktok", settings=cfg)
    assert len(result) <= 5


# ── Unknown platform ───────────────────────────────────────────────────────────

def test_unknown_platform_does_not_raise():
    """Unknown platform must not crash; uses _DEFAULT_CAP."""
    result = _blend(["tagA", "tagB"], "mastodon")
    assert isinstance(result, list)


def test_unknown_platform_cap_is_default():
    from backend.pipeline.hashtag_engine import _DEFAULT_CAP
    many_tags = [f"t{i}" for i in range(100)]
    result = _blend(many_tags, "unknownplatform")
    assert len(result) <= _DEFAULT_CAP


# ── Empty llm_tags ─────────────────────────────────────────────────────────────

def test_empty_llm_tags_returns_curated_only():
    """With no LLM tags, curated pool tags should be returned."""
    pool = ["curatedX", "curatedY", "curatedZ"]
    cfg = {
        "curated_enabled": True,
        "blend_count": 3,
        "pools": {"instagram": pool},
        "blocked": [],
    }
    result = _blend([], "instagram", settings=cfg)
    assert len(result) > 0, "Should return curated tags when llm_tags is empty"
    for tag in result:
        assert tag in pool


# ── Settings unavailable fallback ─────────────────────────────────────────────

def test_settings_unavailable_does_not_crash():
    """If get_setting raises, blend() logs a warning and continues with defaults."""
    from backend.pipeline.hashtag_engine import blend
    with patch("backend.api.routes.settings.get_setting", side_effect=RuntimeError("DB down")):
        result = blend(["tagA", "tagB"], "instagram")
    assert isinstance(result, list)
