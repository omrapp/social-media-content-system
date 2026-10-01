"""Phase 4 (colour + audio) contract tests — no FFmpeg, no DB.

What breaks silently without these:
  * a music level set in the editor never reaches the renderer (the bed just
    plays at 1.0 and nothing errors);
  * `eq` or the duck level is dropped between EDL and EditOverrides, so the
    export looks/sounds different from the preview;
  * a reel merged today stops round-tripping its audio decision tomorrow.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.pipeline.editor_edl import (
    EDL, EqSpec, MusicSpec, Reel, _compile_overrides, hydrate,
)
from backend.scripts.make_lut_previews import preview_name


# ── EDL clamps ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("brightness", 1.5), ("brightness", -1.5),
    ("contrast", 3.5), ("contrast", -0.1),
    ("saturation", 3.5), ("saturation", -0.1),
])
def test_eq_out_of_range_rejected(field, value):
    with pytest.raises(ValidationError):
        EqSpec(**{field: value})


@pytest.mark.parametrize("field,value", [
    ("volume", 2.5), ("volume", -0.1),
    ("fade_s", 5.5), ("duck_volume", 1.5), ("start_offset_s", -1.0),
])
def test_music_out_of_range_rejected(field, value):
    with pytest.raises(ValidationError):
        MusicSpec(**{field: value})


def test_music_defaults_are_the_pre_editor_behaviour():
    m = MusicSpec()
    assert (m.volume, m.fade_s) == (1.0, 1.0)
    # None on both = "let the backend decide", i.e. unchanged from 1.8.0.
    assert m.start_offset_s is None and m.duck_volume is None


# ── EDL -> EditOverrides ─────────────────────────────────────────────────────

def _edl(**reel_kw) -> EDL:
    return EDL(source_media_id="mrg_x", reel=Reel(**reel_kw))


def test_eq_rides_the_overrides_verbatim():
    eq = EqSpec(brightness=-0.12, contrast=1.25, saturation=0.9)
    ov = _compile_overrides(_edl(eq=eq), {})
    assert ov.eq.brightness == pytest.approx(-0.12)
    assert ov.eq.contrast == pytest.approx(1.25)
    assert ov.eq.saturation == pytest.approx(0.9)


def test_duck_volume_none_means_use_the_global_setting():
    ov = _compile_overrides(_edl(music=MusicSpec()), {})
    assert ov.music_duck_volume is None


def test_duck_volume_is_clamped_and_rounded():
    ov = _compile_overrides(_edl(music=MusicSpec(duck_volume=0.123456)), {})
    assert ov.music_duck_volume == pytest.approx(0.123)


def test_unknown_lut_is_rejected_not_silently_dropped():
    from backend.pipeline.editor_edl import EDLError
    with pytest.raises(EDLError):
        _compile_overrides(_edl(lut="../../etc/passwd.cube"), {})


# ── persisted plan -> EDL round trip ─────────────────────────────────────────

def _row_with_audio(audio: dict) -> dict:
    return {
        "id": "mrg_x", "media_type": "VIDEO", "duration_s": 8.0,
        "metadata": {"merge": {
            "graded": False,
            "cuts": [{"src": "a", "start": 0.0, "dur": 8.0, "score": 0.5}],
            "plan": {
                "plan_version": 1,
                "timeline": {"joins": [], "loop_friendly": False},
                "cuts": [{"src_media_id": "a", "start_s": 0.0, "dur_s": 8.0,
                          "score": 0.5, "cleanup": {"pre": "", "post": ""},
                          "fx": {"slow_motion": None, "ken_burns": None}}],
                "audio": audio,
            },
        }},
    }


def test_hydrate_restores_the_audio_decision():
    edl = hydrate(_row_with_audio({
        "enter_offset_s": 4.25, "mode": "music", "fade_s": 2.5, "volume": 0.6,
        "music_path": "/nonexistent/library/bed.m4a",
    }))
    assert edl.approx is False
    assert edl.reel.audio_mode == "music"
    assert edl.reel.music.volume == pytest.approx(0.6)
    assert edl.reel.music.fade_s == pytest.approx(2.5)
    assert edl.reel.music.start_offset_s == pytest.approx(4.25)


def test_hydrate_of_a_pre_phase4_plan_keeps_full_volume():
    # Reels merged before this phase persist only `enter_offset_s`; they must
    # hydrate to an unchanged bed, never to 0.0.
    edl = hydrate(_row_with_audio({"enter_offset_s": 1.0}))
    assert edl.reel.music.volume == pytest.approx(1.0)
    assert edl.reel.audio_mode == "music"


def test_a_muted_bed_is_not_silently_un_muted():
    # `float(x or 1.0)` would turn a deliberate 0.0 back into full volume, both
    # on hydrate and in _cfg_from_plan. Only a MISSING key means "unchanged".
    edl = hydrate(_row_with_audio({"enter_offset_s": 0.0, "volume": 0.0}))
    assert edl.reel.music.volume == pytest.approx(0.0)

    from backend.pipeline.merge_clips import _cfg_from_plan, _music_volume
    cfg = _cfg_from_plan({"audio": {"volume": 0.0}, "timeline": {}, "grade": {}})
    assert cfg["music_volume"] == pytest.approx(0.0)
    assert _music_volume({}) == pytest.approx(1.0)
    assert _music_volume({"music_volume": 0.0}) == pytest.approx(0.0)


def test_original_audio_mode_survives_hydrate():
    edl = hydrate(_row_with_audio({"enter_offset_s": 0.0, "mode": "original"}))
    assert edl.reel.audio_mode == "original"


# ── LUT preview naming (must match ColorVideo.lutPreviewUrl) ─────────────────

@pytest.mark.parametrize("rel,expected", [
    ("warm.cube", "warm.png"),
    ("cinematic/teal_orange.cube", "cinematic__teal_orange.png"),
    ("a/b/c.CUBE", "a__b__c.png"),
])
def test_preview_name_flattens_the_tree(rel, expected):
    assert preview_name(rel) == expected
