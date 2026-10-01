"""Pure-function equivalence tests for the merge_clips decide/filter split.

Pins the decide/filter seam introduced for the v2.0.0 Reel Editor:

    _fx_segment(i, d, cfg, met)        == _fx_filter(_fx_decide(i, cfg, met), d)
    _segment_cleanup(..., cfg, met)    == _cleanup_filters(_cleanup_decide(cfg, met))
    inline (variety, tdurs, tdur)      == _resolve_joins(...)

`_fx_segment` and `_segment_cleanup` are now thin compositions of their own
decide/filter halves, so the first two hold by construction — these tests exist
to keep it that way if anyone re-inlines the logic. `_legacy_joins` is a
standalone reimplementation of the pre-split inline join math, so the third is a
genuine independent check; test_legacy_joins_reference_is_self_consistent guards
that reference against drift in _VARIETY_TRANSITIONS / _FPS.

Every case runs the full flag grid rather than a happy path. No FFmpeg, no cv2,
no DB -- safe to run on every commit.
"""

from __future__ import annotations

import itertools

import pytest

from backend.pipeline import merge_clips as mc

def _met(motion_mag: float, sharp: float = 0.8, expo: float = 0.7,
         bgr: tuple = (110.0, 100.0, 96.0)) -> dict:
    """A _window_metrics-shaped dict. `hist` is deliberately absent: the plan
    drops it (it is a numpy ndarray and makes the plan non-JSON-serializable),
    and neither _fx_segment nor _segment_cleanup reads it."""
    return {"sharp": sharp, "expo": expo, "motion": 0.5,
            "motion_mag": motion_mag, "bgr": bgr}


# --------------------------------------------------------------------------- #
# _fx_segment  ==  _fx_filter(_fx_decide(...))
# --------------------------------------------------------------------------- #

_FX_FLAGS = ("slow_motion", "ken_burns", "adaptive_fx", "smooth_slowmo")
_FX_GRID = list(itertools.product([False, True], repeat=len(_FX_FLAGS)))
_FX_IDX = range(0, 8)
# 0.5 / 2.9 straddle nothing in particular; 3.1 and 6.0 straddle
# smooth_slowmo_max_s (3.0), which gates the minterpolate branch.
_FX_DURS = (0.5, 2.9, 3.1, 6.0)
_FX_METS = (None, _met(0.10), _met(0.35), _met(0.90))


@pytest.mark.parametrize("flags", _FX_GRID, ids=lambda f: "".join("1" if x else "0" for x in f))
def test_fx_decide_filter_matches_fx_segment(flags):
    cfg = dict(zip(_FX_FLAGS, flags))
    cfg.setdefault("slow_motion_factor", 0.85)
    cfg.setdefault("smooth_slowmo_max_s", 3.0)

    mismatches = []
    for idx in _FX_IDX:
        for dur in _FX_DURS:
            for met in _FX_METS:
                expected = mc._fx_segment(idx, dur, cfg, met)
                actual = mc._fx_filter(mc._fx_decide(idx, cfg, met), dur)
                if actual != expected:
                    mismatches.append(
                        f"idx={idx} dur={dur} met={met and met['motion_mag']}\n"
                        f"    expected: {expected}\n"
                        f"    actual:   {actual}")
    assert not mismatches, (
        f"cfg={cfg}\n" + "\n".join(mismatches[:10])
        + (f"\n... and {len(mismatches) - 10} more" if len(mismatches) > 10 else ""))


def test_fx_decide_is_json_serializable():
    """Seam invariant (plan §10 D): the decision must survive a round-trip into
    the persisted plan -- no numpy scalars, no ndarray leaks."""
    import json
    cfg = {"slow_motion": True, "ken_burns": True, "adaptive_fx": True,
           "smooth_slowmo": True, "slow_motion_factor": 0.85,
           "smooth_slowmo_max_s": 3.0}
    for idx in _FX_IDX:
        for met in _FX_METS:
            json.dumps(mc._fx_decide(idx, cfg, met))


# --------------------------------------------------------------------------- #
# _segment_cleanup  ==  _cleanup_filters(_cleanup_decide(...))
# --------------------------------------------------------------------------- #

_CLEAN_FLAGS = ("deblock", "strong_denoise", "color_match", "sharpen", "adaptive_fx")
_CLEAN_GRID = list(itertools.product([False, True], repeat=len(_CLEAN_FLAGS)))
_CLEAN_METS = (
    None,
    _met(0.5, sharp=0.30, expo=0.30),   # dark + soft -> adaptive denoise + cas
    _met(0.5, sharp=0.95, expo=0.80),   # bright + sharp -> neither
)
# _segment_cleanup only touches src/start/dur when met is None AND it needs
# metrics; a path that cannot be opened makes _window_metrics return None, which
# is exactly the "no metrics" case the decider must reproduce.
_NO_SUCH_CLIP = "/nonexistent/golden/equivalence_probe.mp4"


@pytest.mark.parametrize("flags", _CLEAN_GRID,
                         ids=lambda f: "".join("1" if x else "0" for x in f))
def test_cleanup_decide_filters_matches_segment_cleanup(flags):
    cfg = dict(zip(_CLEAN_FLAGS, flags))
    cfg.setdefault("sharpen_amount", 0.3)

    mismatches = []
    for met in _CLEAN_METS:
        expected = mc._segment_cleanup(_NO_SUCH_CLIP, 0.0, 2.0, cfg, met)
        actual = mc._cleanup_filters(mc._cleanup_decide(cfg, met))
        if tuple(actual) != tuple(expected):
            mismatches.append(f"met={met}\n"
                              f"    expected: {expected}\n"
                              f"    actual:   {tuple(actual)}")
    assert not mismatches, f"cfg={cfg}\n" + "\n".join(mismatches)


# --------------------------------------------------------------------------- #
# _resolve_joins  ==  the inline (variety, tdurs, tdur) logic
# --------------------------------------------------------------------------- #

def _legacy_joins(cfg: dict, final_durs: list[float], tdur: float):
    """Verbatim reimplementation of merge_clips.py:1369-1409 -- the render-side
    tdur clamp, the variety list, and the hard-cut-on-beat per-join overlaps."""
    if tdur >= min(final_durs):
        tdur = round(min(final_durs) * 0.4, 3)
    variety = mc._VARIETY_TRANSITIONS if cfg.get("transition_variety") else None
    tdurs = None
    if cfg.get("hard_cuts_on_beat", True) and len(final_durs) > 3:
        hard_td = round(1.0 / mc._FPS, 3)
        tdurs = [(hard_td if (k % 3 == 2) else tdur)
                 for k in range(len(final_durs) - 1)]
    return variety, tdurs, tdur


def _call_resolve_joins(cfg: dict, final_durs: list[float], tdur: float):
    """The plan sketches `_resolve_joins(plan, durs)`; the exact signature is the
    refactor's call. Try the two plausible shapes so this test does not become a
    signature bikeshed -- delete the loser once it lands."""
    try:
        return mc._resolve_joins(cfg, final_durs, tdur)
    except TypeError:
        return mc._resolve_joins({**cfg, "tdur": tdur}, final_durs)


_JOIN_DURS = {
    # n -> (no-clamp durs, clamp-triggering durs where tdur >= min(final_durs))
    2: ([3.0, 2.6], [3.0, 0.4]),
    3: ([2.5, 2.4, 2.6], [2.5, 0.45, 2.6]),
    4: ([2.5, 2.4, 2.6, 2.5], [2.5, 0.3, 2.6, 2.5]),
    7: ([2.5] * 7, [2.5, 2.5, 0.5, 2.5, 2.5, 2.5, 2.5]),
    15: ([2.5] * 15, [2.5] * 14 + [0.49]),
}


@pytest.mark.parametrize("n", sorted(_JOIN_DURS))
@pytest.mark.parametrize("clamped", [False, True], ids=["noclamp", "clamp"])
@pytest.mark.parametrize("hard_cuts", [False, True], ids=["nohard", "hard"])
@pytest.mark.parametrize("variety", [False, True], ids=["novariety", "variety"])
def test_resolve_joins_matches_inline(n, clamped, hard_cuts, variety):
    cfg = {"hard_cuts_on_beat": hard_cuts, "transition_variety": variety}
    final_durs = list(_JOIN_DURS[n][1 if clamped else 0])
    tdur = 0.5

    expected = _legacy_joins(cfg, final_durs, tdur)
    actual = _call_resolve_joins(cfg, final_durs, tdur)

    assert tuple(actual) == tuple(expected), (
        f"n={n} clamped={clamped} hard_cuts={hard_cuts} variety={variety}\n"
        f"  expected (variety, tdurs, tdur): {expected}\n"
        f"  actual:                          {tuple(actual)}")
    # The clamp is the thing that shifts every xfade offset -- assert it landed.
    if clamped:
        assert expected[2] < tdur, "fixture did not actually trigger the clamp"


def test_legacy_joins_reference_is_self_consistent():
    """Not xfail: guards the reference implementation above against drift in
    _VARIETY_TRANSITIONS / _FPS. Runs today, on every commit."""
    variety, tdurs, tdur = _legacy_joins(
        {"hard_cuts_on_beat": True, "transition_variety": True},
        [2.5, 2.5, 2.5, 2.5, 2.5], 0.5)
    assert variety == mc._VARIETY_TRANSITIONS
    assert tdur == 0.5
    assert tdurs == [0.5, 0.5, round(1.0 / mc._FPS, 3), 0.5]

    _, tdurs2, tdur2 = _legacy_joins(
        {"hard_cuts_on_beat": True, "transition_variety": False},
        [2.5, 0.4, 2.5, 2.5], 0.5)
    assert tdur2 == round(0.4 * 0.4, 3)
    assert tdurs2 == [tdur2, tdur2, round(1.0 / mc._FPS, 3)]
