"""
Tests for the 0.4.0 free enhancements:
- video_edit quality filter chain (denoise / sharpen / smooth) + render preset
- resize_clips lanczos scaling
- caption_gen hashtag denylist policy
- settings DEFAULTS carry the new keys
"""
import pytest
from unittest.mock import patch, MagicMock


# ── video_edit quality methods ────────────────────────────────────────────────

def test_apply_denoise_presets():
    from backend.pipeline.video_edit import VideoEditor, _DENOISE_PRESETS
    ed = VideoEditor("in.mp4")
    ed.apply_denoise("medium")
    assert ed.filters == [_DENOISE_PRESETS["medium"]]
    # Unknown strength falls back to light.
    ed2 = VideoEditor("in.mp4")
    ed2.apply_denoise("bogus")
    assert ed2.filters == [_DENOISE_PRESETS["light"]]


def test_apply_sharpen_clamps_amount():
    from backend.pipeline.video_edit import VideoEditor
    ed = VideoEditor("in.mp4")
    ed.apply_sharpen(2.0)            # over-range
    assert ed.filters == ["cas=strength=1.00"]
    ed2 = VideoEditor("in.mp4")
    ed2.apply_sharpen(-1)            # under-range
    assert ed2.filters == ["cas=strength=0.00"]


def test_apply_smooth_builds_minterpolate():
    from backend.pipeline.video_edit import VideoEditor
    ed = VideoEditor("in.mp4")
    ed.apply_smooth(48)
    assert ed.filters == ["minterpolate=fps=48:mi_mode=mci:mc_mode=aobmc"]


def test_render_uses_preset_and_crf():
    from backend.pipeline.video_edit import VideoEditor
    ed = VideoEditor("in.mp4")
    with patch("backend.pipeline.video_edit.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        ed.render("out.mp4", crf=20, preset="medium")
    cmd = run.call_args[0][0]
    assert "-preset" in cmd and cmd[cmd.index("-preset") + 1] == "medium"
    assert "-crf" in cmd and cmd[cmd.index("-crf") + 1] == "20"


def test_resize_uses_lanczos():
    from backend.pipeline import resize_clips
    with patch("backend.pipeline.resize_clips.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        resize_clips.resize("src.mp4", "dst.mp4")
    cmd = run.call_args[0][0]
    vf = cmd[cmd.index("-vf") + 1]
    assert "flags=lanczos" in vf


# ── caption_gen hashtag policy ────────────────────────────────────────────────

def test_dedupe_filter_strips_blocked_and_dupes():
    from backend.pipeline.caption_gen import _dedupe_filter
    blocked = {"travel", "instagood"}
    out = _dedupe_filter(["#Travel", "Kyoto", "kyoto", "instagood", "HiddenGems"], blocked)
    assert out == ["Kyoto", "HiddenGems"]   # blocked + case-insensitive dupe removed, casing kept


def test_apply_hashtag_policy_uses_default_denylist_when_empty():
    from backend.pipeline import caption_gen
    result = {"hashtags_en": ["travel", "japanfood"], "hashtags_en_b": ["nature", "kyotoeats"],
              "hashtags_ar": ["سفر"]}
    with patch.object(caption_gen, "get_setting", return_value={"blocked": []}):
        out = caption_gen._apply_hashtag_policy(result)
    # "travel" + "nature" are in the built-in default denylist; arabic untouched.
    assert out["hashtags_en"] == ["japanfood"]
    assert out["hashtags_en_b"] == ["kyotoeats"]
    assert out["hashtags_ar"] == ["سفر"]


def test_apply_hashtag_policy_respects_configured_blocked():
    from backend.pipeline import caption_gen
    result = {"hashtags_en": ["travel", "kyoto"]}
    with patch.object(caption_gen, "get_setting", return_value={"blocked": ["kyoto"]}):
        out = caption_gen._apply_hashtag_policy(result)
    # Configured list overrides default → "travel" survives, "kyoto" stripped.
    assert out["hashtags_en"] == ["travel"]


# ── generate() Groq primary / OpenRouter fallback ─────────────────────────────

def test_generate_draft_with_groq_calls_groq():
    from backend.pipeline import caption_gen
    fake = {"caption": "hi"}
    with patch.object(caption_gen, "_call_groq_json", return_value=fake) as groq, \
         patch.object(caption_gen, "_call_openrouter") as openrouter:
        out = caption_gen.generate("Japan", "Kyoto", "culture", draft_with_groq=True)
    assert out == fake
    groq.assert_called_once()
    openrouter.assert_not_called()


def test_generate_draft_falls_back_to_openrouter_on_groq_error():
    from backend.pipeline import caption_gen
    fake = {"caption": "from openrouter"}
    with patch.object(caption_gen, "_call_groq_json", side_effect=RuntimeError("boom")), \
         patch.object(caption_gen, "_call_openrouter", return_value=fake) as openrouter:
        out = caption_gen.generate("Japan", "Kyoto", "culture", draft_with_groq=True)
    assert out == fake
    openrouter.assert_called_once()


def test_generate_default_uses_groq_only():
    from backend.pipeline import caption_gen
    fake = {"caption": "h"}
    with patch.object(caption_gen, "_call_groq_json", return_value=fake) as groq, \
         patch.object(caption_gen, "_call_openrouter") as openrouter:
        out = caption_gen.generate("Japan", "Kyoto", "culture")
    assert out == fake
    groq.assert_called_once()
    openrouter.assert_not_called()


# ── settings DEFAULTS ─────────────────────────────────────────────────────────

def test_video_quality_defaults_present():
    from backend.api.routes.settings import DEFAULTS
    v = DEFAULTS["video"]
    for key in ("enhance_quality", "denoise", "denoise_strength", "sharpen",
                "sharpen_amount", "crf", "preset", "smooth_motion", "smooth_fps"):
        assert key in v, f"missing video.{key}"
    assert DEFAULTS["caption"]["draft_with_groq"] is False
    assert DEFAULTS["hashtags"]["blocked"] == []


def test_merge_with_defaults_surfaces_new_keys_in_stale_group():
    # A group seeded earlier with only the old 3 keys must still expose the new
    # quality keys after merge, while keeping the stored override.
    from backend.api.routes.settings import _merge_with_defaults
    stored = {"video": {"auto_stabilize": False}}
    merged = _merge_with_defaults(stored)
    assert merged["video"]["auto_stabilize"] is False          # stored wins
    assert merged["video"]["enhance_quality"] is True          # new default surfaced
    assert "crf" in merged["video"]


def test_merge_with_defaults_preserves_unknown_groups():
    from backend.api.routes.settings import _merge_with_defaults
    merged = _merge_with_defaults({"custom_group": {"x": 1}})
    assert merged["custom_group"] == {"x": 1}
    assert "video" in merged   # defaults still present
