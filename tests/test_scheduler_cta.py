"""
Tests for backend.pipeline.scheduler._build_platform_caption — CTA injection.

Covers:
- CTA not injected when monetize.enabled=False
- CTA injected for instagram when enabled=True
- youtube_link only appended on youtube, absent from instagram
- Platform filter: CTA only on platforms listed in monetize.platforms
"""
import pytest
from unittest.mock import patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build(post: dict, platform: str, monetize_cfg: dict | None = None) -> str:
    """
    Call _build_platform_caption with mocked settings and hashtag blend.
    monetize_cfg: the dict returned by get_setting("monetize"). Defaults to disabled.
    """
    from backend.pipeline.scheduler import _build_platform_caption

    # Default: monetize disabled so tests that don't care about CTA get clean output.
    mon_cfg = monetize_cfg if monetize_cfg is not None else {"enabled": False}

    def fake_get_setting(group):
        if group == "monetize":
            return mon_cfg
        return {}

    # Patch get_setting where it's imported inside _build_platform_caption.
    with patch("backend.db.get_setting", side_effect=fake_get_setting), \
         patch("backend.pipeline.hashtag_engine.blend", return_value=[]):
        return _build_platform_caption(post, platform)


_SAMPLE_POST = {
    "id": "post-001",
    "caption": "Amazing travel clip",
    "caption_ig": "IG version of caption",
    "caption_ig_ar": "نسخة عربية",
    "caption_yt_description": "YouTube description",
    "caption_tt": "TikTok version",
    "hashtags_en": ["travel", "reels"],
    "hashtags_ar": ["سفر"],
    "pillar": "nature",
}


# ── CTA disabled ──────────────────────────────────────────────────────────────

def test_cta_not_injected_when_disabled():
    mon = {"enabled": False, "cta_text": "Link in bio", "platforms": ["instagram"]}
    result = _build(_SAMPLE_POST, "instagram", monetize_cfg=mon)
    assert "Link in bio" not in result


def test_cta_not_injected_when_enabled_false_regardless_of_cta_text():
    mon = {"enabled": False, "cta_text": "Click here!", "platforms": ["instagram", "tiktok"]}
    for platform in ("instagram", "tiktok", "youtube"):
        result = _build(_SAMPLE_POST, platform, monetize_cfg=mon)
        assert "Click here!" not in result, f"CTA should not appear for {platform} when disabled"


# ── CTA injected for instagram ─────────────────────────────────────────────────

def test_cta_injected_for_instagram():
    mon = {
        "enabled": True,
        "cta_text": "Link in bio",
        "platforms": ["instagram", "tiktok", "youtube"],
        "youtube_link": "",
    }
    result = _build(_SAMPLE_POST, "instagram", monetize_cfg=mon)
    assert "Link in bio" in result


def test_cta_injected_for_tiktok():
    mon = {
        "enabled": True,
        "cta_text": "Follow for more",
        "platforms": ["instagram", "tiktok", "youtube"],
        "youtube_link": "",
    }
    result = _build(_SAMPLE_POST, "tiktok", monetize_cfg=mon)
    assert "Follow for more" in result


def test_cta_injected_for_youtube():
    mon = {
        "enabled": True,
        "cta_text": "Subscribe now",
        "platforms": ["instagram", "tiktok", "youtube"],
        "youtube_link": "",
    }
    result = _build(_SAMPLE_POST, "youtube", monetize_cfg=mon)
    assert "Subscribe now" in result


# ── youtube_link only on youtube ──────────────────────────────────────────────

def test_youtube_link_present_in_youtube_caption():
    mon = {
        "enabled": True,
        "cta_text": "Watch more",
        "platforms": ["instagram", "youtube"],
        "youtube_link": "https://youtube.com/@myChannel",
    }
    result = _build(_SAMPLE_POST, "youtube", monetize_cfg=mon)
    assert "https://youtube.com/@myChannel" in result


def test_youtube_link_absent_from_instagram_caption():
    mon = {
        "enabled": True,
        "cta_text": "Watch more",
        "platforms": ["instagram", "youtube"],
        "youtube_link": "https://youtube.com/@myChannel",
    }
    result = _build(_SAMPLE_POST, "instagram", monetize_cfg=mon)
    assert "https://youtube.com/@myChannel" not in result


def test_youtube_link_absent_from_tiktok_caption():
    mon = {
        "enabled": True,
        "cta_text": "Watch more",
        "platforms": ["instagram", "tiktok", "youtube"],
        "youtube_link": "https://youtube.com/@myChannel",
    }
    result = _build(_SAMPLE_POST, "tiktok", monetize_cfg=mon)
    assert "https://youtube.com/@myChannel" not in result


def test_youtube_link_empty_string_not_appended():
    """Empty youtube_link must not append a blank line."""
    mon = {
        "enabled": True,
        "cta_text": "Subscribe",
        "platforms": ["youtube"],
        "youtube_link": "",
    }
    result = _build(_SAMPLE_POST, "youtube", monetize_cfg=mon)
    # The youtube_link itself is empty, but CTA should still appear.
    assert "Subscribe" in result
    # Double-newline at end (blank youtube_link added) should be absent.
    assert not result.endswith("\n\n")


# ── Platform filter ───────────────────────────────────────────────────────────

def test_cta_only_on_listed_platforms_ig_only():
    """CTA only injected for platforms listed in monetize.platforms."""
    mon = {
        "enabled": True,
        "cta_text": "Exclusive offer",
        "platforms": ["instagram"],  # tiktok and youtube excluded
        "youtube_link": "",
    }
    ig_result = _build(_SAMPLE_POST, "instagram", monetize_cfg=mon)
    tt_result = _build(_SAMPLE_POST, "tiktok", monetize_cfg=mon)
    yt_result = _build(_SAMPLE_POST, "youtube", monetize_cfg=mon)

    assert "Exclusive offer" in ig_result, "CTA must appear for instagram (listed)"
    assert "Exclusive offer" not in tt_result, "CTA must NOT appear for tiktok (not listed)"
    assert "Exclusive offer" not in yt_result, "CTA must NOT appear for youtube (not listed)"


def test_cta_only_on_youtube_when_filtered():
    mon = {
        "enabled": True,
        "cta_text": "Watch on YouTube",
        "platforms": ["youtube"],
        "youtube_link": "",
    }
    ig_result = _build(_SAMPLE_POST, "instagram", monetize_cfg=mon)
    yt_result = _build(_SAMPLE_POST, "youtube", monetize_cfg=mon)

    assert "Watch on YouTube" not in ig_result
    assert "Watch on YouTube" in yt_result


def test_empty_platforms_list_no_cta_anywhere():
    """If platforms list is empty, CTA must not appear on any platform."""
    mon = {
        "enabled": True,
        "cta_text": "Nowhere CTA",
        "platforms": [],
        "youtube_link": "https://yt.com/channel",
    }
    for platform in ("instagram", "tiktok", "youtube"):
        result = _build(_SAMPLE_POST, platform, monetize_cfg=mon)
        assert "Nowhere CTA" not in result


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_cta_text_not_appended():
    """If cta_text is empty/whitespace, nothing should be appended."""
    mon = {
        "enabled": True,
        "cta_text": "   ",
        "platforms": ["instagram"],
        "youtube_link": "",
    }
    post = {**_SAMPLE_POST, "caption_ig": "Clean caption", "caption_ig_ar": ""}
    result = _build(post, "instagram", monetize_cfg=mon)
    # Should just be the body + possibly blank lines from empty tags — no stray newlines.
    assert "   " not in result  # whitespace-only cta_text must be stripped and skipped


def test_cta_injection_fallback_on_settings_error():
    """If get_setting raises for monetize, _build_platform_caption must not crash."""
    from backend.pipeline.scheduler import _build_platform_caption

    def raising_get_setting(group):
        if group == "monetize":
            raise RuntimeError("DB error")
        return {}

    with patch("backend.api.routes.settings.get_setting", side_effect=raising_get_setting), \
         patch("backend.pipeline.hashtag_engine.blend", return_value=[]):
        result = _build_platform_caption(_SAMPLE_POST, "instagram")
    assert isinstance(result, str)
