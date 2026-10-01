"""Contract between merge_clips.render() and editor_edl.hydrate().

render() persists a trimmed PLAN v1 at `metadata.merge.plan`; hydrate() prefers
it over the lossy `metadata.merge.cuts` spine and only then marks a doc
approx=True. The failure mode is silent: rename a field on either side and
hydrate quietly falls back to the approximate path, so reels stop round-tripping
exactly and nothing errors. These tests make that loud.

No FFmpeg, no DB — safe on every commit.
"""

from __future__ import annotations

import pytest

from backend.pipeline.editor_edl import hydrate


def _plan_row() -> dict:
    """A media row shaped exactly as render() writes it (field names verbatim)."""
    return {
        "id": "mrg_abc123", "media_type": "VIDEO", "duration_s": 30.63,
        "country": "Japan", "city": "Kyoto", "pillar": "nature",
        "metadata": {"merge": {
            "source_ids": ["jp_local_01", "jp_stock_00"], "sources": 2,
            "graded": False, "grade": "", "transition": "fade", "n": 2,
            "audio": "music", "music_path": "golden_bed.m4a", "loop_friendly": False,
            "fx": {"ken_burns": True, "adaptive_fx": True, "deband": False,
                   "transition_variety": True, "hard_cuts_on_beat": True},
            "cuts": [
                {"src": "jp_local_01", "start": 0.0, "dur": 7.933, "score": 0.793},
                {"src": "jp_stock_00", "start": 0.0, "dur": 7.933, "score": 0.708},
            ],
            "plan": {
                "plan_version": 1,
                "timeline": {"joins": [{"name": "dissolve", "duration_s": 0.5}],
                             "loop_friendly": False},
                "cuts": [
                    {"src_media_id": "jp_local_01", "start_s": 0.0, "dur_s": 7.933,
                     "score": 0.793,
                     "cleanup": {"pre": "deblock=filter=strong:block=8", "post": ""},
                     "fx": {"slow_motion": None, "ken_burns": None}},
                    {"src_media_id": "jp_stock_00", "start_s": 0.0, "dur_s": 7.933,
                     "score": 0.708,
                     "cleanup": {"pre": "", "post": "cas=0.40"},
                     "fx": {"slow_motion": {"factor": 0.85, "smooth": False,
                                            "smooth_max_s": 3.0},
                            "ken_burns": {"direction": "out", "drift": 1}}},
                ],
                "audio": {"enter_offset_s": 2.5},
            },
        }},
    }


def test_persisted_plan_round_trips_exactly():
    edl = hydrate(_plan_row())
    assert edl.approx is False, (
        "hydrate fell back to the lossy `cuts` path — a PLAN field name almost "
        "certainly drifted between merge_clips.render and editor_edl")
    assert len(edl.cuts) == 2


def test_per_cut_fx_survives_the_round_trip():
    """Per-cut slow-mo and Ken Burns are exactly what the legacy `cuts` spine
    cannot express — losing them is the whole reason `plan` exists."""
    c0, c1 = hydrate(_plan_row()).cuts

    assert c0.speed == 1.0
    assert c0.ken_burns.enabled is False

    assert c1.speed == pytest.approx(0.85)
    assert c1.ken_burns.enabled is True
    assert c1.ken_burns.direction == "out"
    assert c1.ken_burns.drift == 1


def test_joins_come_from_the_plan_not_the_reel_level_transition():
    """metadata.merge.transition is 'fade'; the plan's join says 'dissolve'.
    Reading the reel-level value would look right on a single-transition reel
    and silently flatten every varied one."""
    c0 = hydrate(_plan_row()).cuts[0]
    assert c0.transition.name == "dissolve"
    assert c0.transition.duration_s == pytest.approx(0.5)


def test_legacy_row_without_plan_is_marked_approx():
    row = _plan_row()
    del row["metadata"]["merge"]["plan"]
    edl = hydrate(row)
    assert edl.approx is True, (
        "a pre-2.0.0 reel has no persisted plan and MUST be flagged approximate "
        "so the UI can warn that exporting will not reproduce it exactly")
    assert len(edl.cuts) == 2
