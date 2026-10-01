"""Golden regression harness for backend/pipeline/merge_clips.py.

`merge_clips.run()` is being split into `build_plan()` + `render(plan)` for the
v2.0.0 Reel Editor. The split must be pure code motion. Byte identity of the
output MP4 is not provable across FFmpeg builds, so the load-bearing assertion
here is:

    the ordered list of subprocess argv invocations is identical
    string-for-string, and the media row written by upsert_media()
    (metadata.merge included) is identical.

Two modes:

    capture   MERGE_GOLDEN=capture pytest tests/test_merge_golden.py -m slow
              (or: pytest tests/test_merge_golden.py -m slow --update-golden)
              writes tests/fixtures/merge_golden/<case>.argv.json + .meta.json

    assert    pytest tests/test_merge_golden.py -m slow          [default]
              compares against the committed fixtures

CAPTURE MUST RUN AT PRE-REFACTOR HEAD. Goldens captured after any change to
merge_clips.py describe the new behavior, not the old one, and the whole
exercise is worthless. See tests/README_merge_golden.md.
"""

from __future__ import annotations

import os

import pytest

from tests.conftest_merge import (  # noqa: F401  (merge_deterministic is a fixture)
    diff_argv,
    media_row,
    merge_deterministic,
    read_golden,
    write_golden,
)
from tests.fixtures.clips import make_clips

pytestmark = pytest.mark.slow


def _capture_mode(request) -> bool:
    if os.environ.get("MERGE_GOLDEN", "").lower() in {"capture", "update", "1"}:
        return True
    try:
        return bool(request.config.getoption("--update-golden"))
    except (ValueError, AttributeError):
        # Option not registered (bare `pytest` from the repo root); the env var
        # is the always-available switch.
        return False


# --------------------------------------------------------------------------- #
# Pools
# --------------------------------------------------------------------------- #

# Captions chosen so mood_from_text() lands on a stable, non-None mood, and so
# the Iceland ghost row in case 15 pushes it somewhere DIFFERENT -- that is what
# makes a regression in the rows-vs-cuts aggregation visible.
_JP_CAPTION = "ancient temple heritage walk, quiet tradition"
_IS_CAPTION = "breathtaking waterfall, majestic canyon view"


def _japan_pool() -> list[dict]:
    """24 Japan rows (12 local + 12 stock, interleaved) cycling the four main
    fixture clips. Distinct hook scores so the opener-pinning step at
    merge_clips.py:1194-1201 has an unambiguous winner.

    All rows share category="Japan" -- that is the field get_category_raw_media
    pins the pool on (db.get_category_raw_media / conftest's fake), so it can't
    vary per row the way the old per-row city/pillar did. The old city/pillar
    cycling is dropped rather than folded into tags: with a top-level
    `category` always passed by every case below, `category or
    _dominant_category(rows)` short-circuits on the truthy top-level value, so
    a per-row secondary axis here would no longer feed any code path (unlike
    the old country-pins-pool / pillar-drives-dominant-music split)."""
    clips = make_clips.MAIN_CLIPS
    rows: list[dict] = []
    for i in range(12):
        rows.append(media_row(
            f"jp_local_{i:02d}", clips[i % len(clips)],
            category="Japan",
            source="upload",
            hook_score=round(0.30 + 0.03 * i, 3),
            quality_score=round(0.40 + 0.02 * i, 3),
            caption=_JP_CAPTION,
            tags=["temple", "kyoto"],
            duration_s=12.0,
        ))
        rows.append(media_row(
            f"jp_stock_{i:02d}", clips[(i + 2) % len(clips)],
            category="Japan",
            source="stock",
            hook_score=round(0.25 + 0.02 * i, 3),
            quality_score=round(0.35 + 0.03 * i, 3),
            caption=_JP_CAPTION,
            tags=["temple"],
            duration_s=12.0,
        ))
    return rows


def _iceland_short_pool() -> list[dict]:
    """Three ~1.6 s clips -- far too little footage for a 20 s target, so the
    min-duration guarantee at merge_clips.py:1301-1339 has to loop the montage."""
    return [
        media_row(f"is_short_{i}", name, category="Iceland", source="upload",
                  hook_score=round(0.5 + 0.1 * i, 3),
                  quality_score=round(0.4 + 0.1 * i, 3),
                  caption=_IS_CAPTION, tags=["waterfall"], duration_s=1.6)
        for i, name in enumerate(make_clips.SHORT_CLIPS)
    ]


def _handpick_rows(n: int = 3) -> list[dict]:
    clips = make_clips.MAIN_CLIPS
    return [
        media_row(f"hp_{i:02d}", clips[i % len(clips)],
                  category="Japan", source="upload",
                  hook_score=round(0.60 - 0.05 * i, 3),
                  quality_score=round(0.55 - 0.05 * i, 3),
                  caption=_JP_CAPTION, tags=["temple"], duration_s=12.0)
        for i in range(n)
    ]


# Keeps the focused cases cheap: without it, split_stock_local forces 20 resolved
# sources (8 stock + 12 local) and every one of them gets cv2-scored. Case 02
# deliberately keeps the production defaults so that path is covered too.
_LEAN = {"min_main_videos": 4, "split_stock_local": False}


# --------------------------------------------------------------------------- #
# The 15 cases
# --------------------------------------------------------------------------- #
# Each builder wires the harness and returns the kwargs for merge_clips.run().

def _c01_handpick_inline(h):
    """Hand-pick 3 ids, stock defaults -> n <= _XFADE_MAX_INLINE, monolithic
    xfade graph (not the incremental fold)."""
    rows = _handpick_rows(3)
    h.register(rows)
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"media_ids": [r["id"] for r in rows], "settings": {}}


def _c02_auto_n15_fold(h):
    """Auto-select, 15 cuts -> _incremental_xfade fold path. Production defaults
    (split_stock_local on) so the stock/local quota is covered here."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 15, "settings": {}}


def _c03_adaptive_fx_on(h):
    """Per-clip content-adaptive FX (cv2 present): slow-mo / Ken Burns / denoise
    / cas chosen from each clip's own metrics."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "adaptive_fx": True}}


def _c04_adaptive_fx_off(h):
    """Legacy fixed idx-parity FX: slow-mo on even indexes, Ken Burns on all."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "adaptive_fx": False}}


def _c05_grade_grain_vignette(h):
    """Post-montage grade profile + grain + vignette -> the [vout]->[vgrade] tail
    and graded=True (downstream LUT skipped)."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "grade": "golden_hour",
                         "grain": True, "vignette": True}}


def _c06_no_grade(h):
    """No grade, no grain, no vignette, no deband -> _grade_chain returns "" and
    the filtergraph has no grade tail at all."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "grade": "", "grain": False,
                         "vignette": False, "deband": False}}


def _c07_audio_original(h):
    """audio_mode=original -> the longest cut's own source file is the audio
    input, no -ss enter offset."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "audio_mode": "original"}}


def _c08_audio_music_explicit(h):
    """Explicit music_path -> _safe_music_path containment + the -stream_loop /
    -ss / atrim / afade audio tail."""
    h.set_pool(_japan_pool())
    h.track_result = None  # must not be needed; the explicit path wins
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "audio_mode": "music", "beat_sync": False,
                         "music_path": make_clips.MUSIC_BED}}


def _c09_audio_none_anullsrc(h):
    """No music available at all -> the anullsrc silent-bed branch."""
    h.set_pool(_japan_pool())
    h.track_result = None
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "audio_mode": "music", "beat_sync": False}}


def _c10_beat_sync(h):
    """beat_sync on -> _beat_segment_durations drives per-cut lengths and the
    picked track doubles as the music bed."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "beat_sync": True}}


def _c11_loop_friendly(h):
    """loop_friendly -> opener echoed as the final cut and the music fade-out
    suppressed."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "loop_friendly": True}}


def _c12_hard_cuts_off(h):
    """hard_cuts_on_beat off with >3 cuts -> tdurs is None, every join uses the
    constant transition duration."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 5,
            "settings": {**_LEAN, "hard_cuts_on_beat": False}}


def _c13_thin_pool_min_duration(h):
    """Thin pool of very short clips -> the min-duration guarantee fires and
    loops the montage until it can fill the target."""
    h.set_pool(_iceland_short_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Iceland",
            "settings": {**_LEAN, "target_duration_s": 20.0}}


def _c14_cleanup_filters(h):
    """color_match + sharpen + deblock with adaptive off -> a non-empty (pre,
    post) pair wrapped around _NORM_FILTER on every segment."""
    h.set_pool(_japan_pool())
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    return {"category": "Japan", "count": 4,
            "settings": {**_LEAN, "adaptive_fx": False, "color_match": True,
                         "sharpen": True, "sharpen_amount": 0.3,
                         "deblock": True, "strong_denoise": False}}


def _c15_missing_source_row(h):
    """THE important one. A resolved source row whose file is missing on disk.

    _source_path() returns None for it, so it contributes no cut -- but it stays
    in `rows`, and _first_of() / _dominant_category() / the mood-text aggregation
    all iterate `rows`, not cuts. Deriving those from plan.cuts after the
    refactor would silently change the reel's category/tags and the
    auto-picked music. The ghost row is FIRST in the hand-pick order and
    carries a distinct category ("Iceland" vs. the other three rows'
    "Japan") + caption, so a regression shows up in both <case>.meta.json's
    upsert payload (category="Iceland", from _first_of -- the ghost wins) and
    its recorded track_calls (category="Japan", from _dominant_category --
    the 3-vs-1 majority wins): those two must legitimately DISAGREE for this
    case to prove anything.
    """
    ghost = media_row("hp_ghost", "/nonexistent/golden/missing_source.mp4",
                      category="Iceland",
                      source="upload", hook_score=0.99, quality_score=0.99,
                      caption=_IS_CAPTION, tags=["waterfall"], duration_s=9.0)
    rows = [ghost] + _handpick_rows(3)
    h.register(rows)
    h.track_result = str(make_clips.MUSIC_DIR / make_clips.MUSIC_BED)
    # beat_sync off so the auto-pick (category / mood, all derived from
    # `rows`) actually runs and is recorded in track_calls.
    return {"media_ids": [r["id"] for r in rows],
            "settings": {"beat_sync": False}}


CASES = {
    "01_handpick_inline_xfade": _c01_handpick_inline,
    "02_auto_n15_fold": _c02_auto_n15_fold,
    "03_adaptive_fx_on": _c03_adaptive_fx_on,
    "04_adaptive_fx_off": _c04_adaptive_fx_off,
    "05_grade_grain_vignette": _c05_grade_grain_vignette,
    "06_no_grade": _c06_no_grade,
    "07_audio_original": _c07_audio_original,
    "08_audio_music_explicit": _c08_audio_music_explicit,
    "09_audio_none_anullsrc": _c09_audio_none_anullsrc,
    "10_beat_sync": _c10_beat_sync,
    "11_loop_friendly": _c11_loop_friendly,
    "12_hard_cuts_off": _c12_hard_cuts_off,
    "13_thin_pool_min_duration": _c13_thin_pool_min_duration,
    "14_cleanup_filters": _c14_cleanup_filters,
    "15_missing_source_row": _c15_missing_source_row,
}


@pytest.mark.parametrize("case", list(CASES))
def test_merge_golden(case, merge_deterministic, request):
    h = merge_deterministic
    kwargs = CASES[case](h)

    result = h.run_case(case, **kwargs)
    assert result.get("status") == "completed", f"{case}: merge did not complete: {result}"
    assert h.calls, f"{case}: no subprocess invocations captured"
    assert h.upserts, f"{case}: upsert_media was never called"

    argv_actual = h.argv_payload()
    meta_actual = h.meta_payload()

    if _capture_mode(request):
        write_golden(case, argv_actual, meta_actual)
        pytest.skip(f"captured golden for {case} "
                    f"({len(argv_actual)} invocations, {len(h.upserts)} upsert)")

    argv_expected, meta_expected = read_golden(case)
    assert argv_actual == argv_expected, diff_argv(case, argv_expected, argv_actual)
    assert meta_actual == meta_expected, (
        f"metadata mismatch for golden case '{case}'\n"
        f"  expected: {meta_expected}\n"
        f"  actual:   {meta_actual}"
    )


def test_all_cases_have_goldens(request):
    """Fails loudly if a case was added without capturing its fixture (or a
    fixture was deleted). Cheap -- no ffmpeg."""
    if _capture_mode(request):
        pytest.skip("capture mode")
    from tests.conftest_merge import golden_paths
    missing = [c for c in CASES if not all(p.exists() for p in golden_paths(c))]
    assert not missing, (
        "missing golden fixtures for: " + ", ".join(missing) +
        "\ncapture them at PRE-REFACTOR HEAD: "
        "MERGE_GOLDEN=capture pytest tests/test_merge_golden.py -m slow"
    )
