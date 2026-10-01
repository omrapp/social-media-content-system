"""
Tests for the 0.6.0 video-selection enhancements:
- db._passes_quality_gate null-safe matrix
- flag_unusable._reason hard present-field rules
- quality_probe score normalization + measure-only vs reject behaviour
"""
import pytest
from unittest.mock import patch


# ── selection quality gate (null-safe) ─────────────────────────────────────────

GATE_CFG = {
    "min_duration_s": 10.0,
    "min_short_side": 720.0,
    "min_hook_score": 0.0,      # disabled
    "min_quality_score": 0.0,   # disabled
    "require_video_only": True,
}


def _gate(row, cfg=None):
    from backend.db import _passes_quality_gate
    return _passes_quality_gate(row, cfg or GATE_CFG)


def test_gate_rejects_present_short_duration():
    ok, reason = _gate({"media_type": "VIDEO", "duration_s": 4.0})
    assert ok is False
    assert reason.startswith("too_short")


def test_gate_passes_present_long_duration():
    ok, reason = _gate({"media_type": "VIDEO", "duration_s": 20.0, "width": 1080, "height": 1920})
    assert ok is True
    assert reason is None


def test_gate_missing_duration_never_rejects():
    # duration_s absent → that rule cannot fail.
    ok, _ = _gate({"media_type": "VIDEO", "width": 1080, "height": 1920})
    assert ok is True


def test_gate_rejects_low_resolution():
    ok, reason = _gate({"media_type": "VIDEO", "duration_s": 20.0, "width": 480, "height": 640})
    assert ok is False
    assert reason.startswith("low_res")


def test_gate_missing_dimensions_never_rejects():
    ok, _ = _gate({"media_type": "VIDEO", "duration_s": 20.0})
    assert ok is True


def test_gate_rejects_non_video_when_required():
    ok, reason = _gate({"media_type": "IMAGE", "duration_s": 20.0})
    assert ok is False
    assert reason == "not_video"


def test_gate_allows_unknown_media_type():
    # media_type None (column not selected) is tolerated.
    ok, _ = _gate({"duration_s": 20.0, "width": 1080, "height": 1920})
    assert ok is True


def test_gate_hook_score_disabled_at_zero():
    ok, _ = _gate({"media_type": "VIDEO", "duration_s": 20.0, "hook_score": 0.01})
    assert ok is True


def test_gate_hook_score_rejects_when_enabled():
    cfg = {**GATE_CFG, "min_hook_score": 0.5}
    ok, reason = _gate({"media_type": "VIDEO", "duration_s": 20.0, "hook_score": 0.2}, cfg)
    assert ok is False
    assert reason.startswith("low_hook_score")


def test_gate_quality_score_measure_only_at_zero():
    ok, _ = _gate({"media_type": "VIDEO", "duration_s": 20.0, "quality_score": 0.01})
    assert ok is True


def test_gate_quality_score_rejects_when_enabled():
    cfg = {**GATE_CFG, "min_quality_score": 0.4}
    ok, reason = _gate({"media_type": "VIDEO", "duration_s": 20.0, "quality_score": 0.1}, cfg)
    assert ok is False
    assert reason.startswith("low_quality")


# ── flag_unusable hard rules ────────────────────────────────────────────────────

FLAG_THR = {"min_duration_s": 10.0, "min_short_side": 720.0}


def test_flag_reason_too_short():
    from backend.pipeline.flag_unusable import _reason
    assert _reason({"duration_s": 3.0}, FLAG_THR).startswith("too_short")


def test_flag_reason_low_res():
    from backend.pipeline.flag_unusable import _reason
    assert _reason({"duration_s": 30, "width": 360, "height": 640}, FLAG_THR).startswith("low_res")


def test_flag_reason_none_when_ok():
    from backend.pipeline.flag_unusable import _reason
    assert _reason({"duration_s": 30, "width": 1080, "height": 1920}, FLAG_THR) is None


def test_flag_reason_missing_data_never_flags():
    from backend.pipeline.flag_unusable import _reason
    assert _reason({}, FLAG_THR) is None


# ── quality_probe normalization ─────────────────────────────────────────────────

def test_probe_file_perfect_scores():
    import backend.pipeline.quality_probe as qp
    with patch.object(qp, "_ffmpeg_available", return_value=True), \
         patch.object(qp, "_signalstats_yavg", return_value=qp._SHARP_REF), \
         patch.object(qp, "_signalstats_ydif", return_value=0.0):
        scores = qp.probe_file(qp.Path("x.mp4"))
    assert scores["blur_score"] == 1.0
    assert scores["shake_score"] == 1.0
    assert scores["quality_score"] == 1.0


def test_probe_file_mid_scores():
    import backend.pipeline.quality_probe as qp
    with patch.object(qp, "_ffmpeg_available", return_value=True), \
         patch.object(qp, "_signalstats_yavg", return_value=qp._SHARP_REF / 2), \
         patch.object(qp, "_signalstats_ydif", return_value=qp._SHAKE_REF / 2):
        scores = qp.probe_file(qp.Path("x.mp4"))
    assert scores["blur_score"] == 0.5
    assert scores["shake_score"] == 0.5
    assert scores["quality_score"] == 0.5


def test_probe_file_none_when_unmeasurable():
    import backend.pipeline.quality_probe as qp
    with patch.object(qp, "_ffmpeg_available", return_value=True), \
         patch.object(qp, "_signalstats_yavg", return_value=None), \
         patch.object(qp, "_signalstats_ydif", return_value=None):
        assert qp.probe_file(qp.Path("x.mp4")) is None


# ── quality_probe enforcement ───────────────────────────────────────────────────

def test_score_one_measure_only_does_not_reject():
    import backend.pipeline.quality_probe as qp
    row = {"id": "m1", "media_type": "VIDEO", "quality_score": 0.1}
    with patch.object(qp, "update_media") as upd:
        out = qp._score_one(row, {"min_quality_score": 0.0}, force=False)
    assert out["quality_score"] == 0.1
    upd.assert_not_called()  # already scored + measure-only → no write


def test_score_one_rejects_and_flags_below_threshold():
    import backend.pipeline.quality_probe as qp
    row = {"id": "m1", "media_type": "VIDEO", "quality_score": 0.1}
    with patch.object(qp, "update_media") as upd:
        with pytest.raises(qp.QualityRejected):
            qp._score_one(row, {"min_quality_score": 0.5}, force=False)
    upd.assert_called_once_with("m1", {"do_not_use": 1})


def test_score_one_skips_non_video():
    import backend.pipeline.quality_probe as qp
    out = qp._score_one({"id": "m1", "media_type": "IMAGE"}, {"min_quality_score": 0.5}, force=False)
    assert out.get("skipped") == "not_video"
