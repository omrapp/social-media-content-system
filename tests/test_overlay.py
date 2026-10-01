"""
Unit tests for backend/pipeline/overlay.py.

Pure functions — no DB, no settings, no FFmpeg execution.
"""
import pytest

from backend.pipeline.overlay import (
    _escape_drawtext, _css_to_ffmpeg_color, format_tags, build_branding_filters,
)


# ── _escape_drawtext ──────────────────────────────────────────────────────────

def test_escape_drawtext_plain():
    assert _escape_drawtext("Hello World") == "Hello World"


def test_escape_drawtext_at_sign_not_escaped():
    # @ is not an FFmpeg drawtext metacharacter.
    assert _escape_drawtext("@myhandle") == "@myhandle"


def test_escape_drawtext_colon():
    assert _escape_drawtext("time:00") == "time\\:00"


def test_escape_drawtext_percent():
    assert _escape_drawtext("50%") == "50\\%"


def test_escape_drawtext_single_quote():
    assert _escape_drawtext("it's") == "it\\'s"


def test_escape_drawtext_backslash():
    assert _escape_drawtext("a\\b") == "a\\\\b"


def test_escape_drawtext_backslash_before_percent():
    # backslash must be escaped before % to avoid double-escaping.
    result = _escape_drawtext("\\%")
    assert result == "\\\\\\%"


# ── _css_to_ffmpeg_color ──────────────────────────────────────────────────────

def test_css_to_ffmpeg_white_opaque():
    assert _css_to_ffmpeg_color("#ffffff") == "0xFFFFFF"


def test_css_to_ffmpeg_black_opaque():
    assert _css_to_ffmpeg_color("#000000") == "0x000000"


def test_css_to_ffmpeg_with_opacity():
    result = _css_to_ffmpeg_color("#ffffff", 0.7)
    assert result == "0xFFFFFF@0.70"


def test_css_to_ffmpeg_named_color_passthrough():
    assert _css_to_ffmpeg_color("white") == "white"


def test_css_to_ffmpeg_named_with_opacity():
    assert _css_to_ffmpeg_color("black", 0.5) == "black@0.50"


def test_css_to_ffmpeg_fully_opaque_no_suffix():
    assert "@" not in _css_to_ffmpeg_color("#aabbcc", 1.0)


# ── format_tags ────────────────────────────────────────────────────────────────

def test_format_tags_multiple():
    assert format_tags(["Kyoto", "Japan"]) == "Kyoto, Japan"


def test_format_tags_single():
    assert format_tags(["Japan"]) == "Japan"


def test_format_tags_skips_empty_string():
    assert format_tags(["", "Japan"]) == "Japan"


def test_format_tags_skips_none():
    assert format_tags([None, "Japan"]) == "Japan"


def test_format_tags_skips_whitespace():
    assert format_tags(["  ", "Japan"]) == "Japan"


def test_format_tags_none_input():
    assert format_tags(None) is None


def test_format_tags_empty_list():
    assert format_tags([]) is None


def test_format_tags_all_empty():
    assert format_tags(["", "  "]) is None


def test_format_tags_no_leading_comma():
    # Regression guard for the original add_location_text() bug.
    result = format_tags(["", "Japan"])
    assert result is not None
    assert not result.startswith(",")


def test_format_tags_raw_string_passthrough():
    # SQLite fallback may hand back an already-joined/raw string.
    assert format_tags("Kyoto, Japan") == "Kyoto, Japan"


# ── build_branding_filters ────────────────────────────────────────────────────

FONT = "/fonts/PlayfairDisplay-SemiBold.ttf"


def test_all_empty_returns_empty():
    # No location, no handle, no custom_text → nothing to draw.
    assert build_branding_filters(None, "", font_path=FONT) == []
    assert build_branding_filters(None, None, font_path=FONT) == []
    assert build_branding_filters(None, "   ", font_path=FONT) == []
    assert build_branding_filters("", "", font_path=FONT) == []


def test_location_only_draws_two_elements():
    # Location without handle → drawbox + location text (no handle filter).
    filters = build_branding_filters("Kyoto, Japan", "", font_path=FONT)
    assert len(filters) == 2
    assert filters[0].startswith("drawbox=")
    assert "Kyoto, Japan" in filters[1]


def test_full_filters_returns_three_elements():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT)
    assert len(filters) == 3


def test_drawbox_is_first():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT)
    assert filters[0].startswith("drawbox=")


def test_drawbox_default_color_is_white_hex():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT)
    box = filters[0]
    assert "0xFFFFFF" in box
    assert "t=fill" in box


def test_drawbox_bottom_anchored():
    filters = build_branding_filters("Kyoto, Japan", "@me", bar_h=45, font_path=FONT)
    box = filters[0]
    assert "y=ih-45" in box
    assert "h=45" in box


def test_drawbox_top_position():
    filters = build_branding_filters("Kyoto, Japan", "@me", bar_h=45, font_path=FONT, bar_position="top")
    box = filters[0]
    assert "y=0" in box


def test_drawtext_default_color_is_black_hex():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT)
    for f in filters[1:]:
        assert "0x000000" in f


def test_location_text_left_aligned_by_default():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT)
    loc_filter = filters[1]
    assert "drawtext=" in loc_filter
    assert "x=24" in loc_filter


def test_handle_text_right_aligned_by_default():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT)
    handle_filter = filters[2]
    assert "drawtext=" in handle_filter
    assert "x=w-text_w-24" in handle_filter


def test_location_side_right():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT, location_side="right")
    loc_filter = filters[1]
    assert "x=w-text_w-24" in loc_filter


def test_handle_side_left():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT, handle_side="left")
    handle_filter = filters[2]
    assert "x=24" in handle_filter


def test_all_drawtext_have_fontfile():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT)
    for f in filters[1:]:
        assert f"fontfile='{FONT}'" in f


def test_null_location_returns_two_elements():
    # No location: box + handle only (still branded).
    filters = build_branding_filters(None, "@me", font_path=FONT)
    assert len(filters) == 2
    assert filters[0].startswith("drawbox=")
    assert "x=w-text_w-24" in filters[1]


def test_colon_in_handle_escaped():
    filters = build_branding_filters(None, "@me:test", font_path=FONT)
    handle_filter = filters[1]
    assert "\\:" in handle_filter
    assert "@me:test" not in handle_filter


def test_custom_text_adds_filter():
    # location + handle + custom_text → drawbox + location + handle + custom = 4
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT, custom_text="travel.example.com")
    assert len(filters) == 4
    assert any("travel.example.com" in f for f in filters)


def test_custom_text_without_handle():
    # location + custom_text, no handle → drawbox + location + custom = 3
    filters = build_branding_filters("Kyoto, Japan", "", font_path=FONT, custom_text="my tagline")
    assert len(filters) == 3
    assert any("my tagline" in f for f in filters)


def test_custom_text_only_returns_two_elements():
    # custom_text alone, no location/handle → drawbox + custom = 2
    filters = build_branding_filters(None, "", font_path=FONT, custom_text="my tagline")
    assert len(filters) == 2
    assert any("my tagline" in f for f in filters)


def test_empty_custom_text_ignored():
    filters = build_branding_filters("Kyoto, Japan", "@me", font_path=FONT, custom_text="")
    assert len(filters) == 3  # same as without custom_text


def test_bar_height_param_scales():
    filters = build_branding_filters("Japan", "@me", bar_h=90, font_path=FONT)
    assert "y=ih-90" in filters[0]
    assert "h=90" in filters[0]
    # font_size should be int(90 * 0.58) = 52
    assert "fontsize=52" in filters[1]


def test_custom_bar_color_hex():
    filters = build_branding_filters("Japan", "@me", font_path=FONT, bar_bg_color="#1a2b3c")
    assert "0x1A2B3C" in filters[0]


def test_bar_opacity_in_drawbox():
    filters = build_branding_filters("Japan", "@me", font_path=FONT, bar_opacity=0.7)
    assert "@0.70" in filters[0]


def test_full_opacity_no_at_suffix_in_drawbox():
    filters = build_branding_filters("Japan", "@me", font_path=FONT, bar_opacity=1.0)
    assert "@" not in filters[0]


def test_custom_text_color():
    filters = build_branding_filters("Japan", "@me", font_path=FONT, text_color="#ff0000")
    # All drawtext filters should use the custom text color
    for f in filters[1:]:
        assert "0xFF0000" in f
