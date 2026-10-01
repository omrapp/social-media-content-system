"""
LUT validation + render-fallback regression tests (v0.9.5).

Root cause of the v0.9.5 edit-stage crash: assets/luts/*.cube were stub files
(header "LUT_3D_SIZE 17" but only ~306 of the required 4913 data rows). FFmpeg's
lut3d filter aborts mid-graph with "Unexpected EOF", failing the whole render —
and the retry fallback only stripped zoompan, so it failed again with the LUT
still in the chain. Fixes pinned here:
  1. valid_cube() rejects truncated / stub / missing .cube files.
  2. apply_lut() skips the grade (no lut3d filter) when the file is invalid.
  3. render() progressively strips zoompan THEN lut3d on failure.
"""
from unittest.mock import MagicMock, patch

import pytest

from backend.config import LUTS_DIR, LUTS_CINEMATIC_DIR
from backend.pipeline.video_edit import VideoEditor, valid_cube


def _complete_cube(path, size=2):
    rows = [f"# test", f'TITLE "T"', f"LUT_3D_SIZE {size}", ""]
    for _ in range(size ** 3):
        rows.append("0.500000 0.500000 0.500000")
    path.write_text("\n".join(rows) + "\n")


def _stub_cube(path, size=17, rows=10):
    body = "\n".join(["0.5 0.5 0.5"] * rows)
    path.write_text(f'TITLE "Stub"\nLUT_3D_SIZE {size}\n\n{body}\n')


# ── valid_cube ──────────────────────────────────────────────────────────────

def test_valid_cube_true_for_complete(tmp_path):
    f = tmp_path / "good.cube"
    _complete_cube(f, size=4)
    assert valid_cube(f) is True


def test_valid_cube_false_for_truncated_stub(tmp_path):
    f = tmp_path / "stub.cube"
    _stub_cube(f, size=17, rows=10)  # needs 4913, has 10
    assert valid_cube(f) is False


def test_valid_cube_false_for_missing(tmp_path):
    assert valid_cube(tmp_path / "nope.cube") is False


def test_valid_cube_false_for_empty(tmp_path):
    f = tmp_path / "empty.cube"
    f.write_text("")
    assert valid_cube(f) is False


def test_shipped_luts_are_valid():
    """The .cube files committed in assets/luts/ must be complete (not stubs)."""
    cubes = list(LUTS_DIR.glob("*.cube"))
    assert cubes, "no .cube files found in assets/luts/"
    for c in cubes:
        assert valid_cube(c), f"{c.name} is not a complete 3D LUT"


def test_cinematic_luts_are_valid():
    """Every curated cinematic LUT (once curation has run) must be complete."""
    cubes = list(LUTS_CINEMATIC_DIR.glob("*.cube"))
    if not cubes:
        pytest.skip("no cinematic LUTs yet — run backend.scripts.curate_luts --apply")
    for c in cubes:
        assert valid_cube(c), f"{c.name} is not a complete 3D LUT"


# ── apply_lut ───────────────────────────────────────────────────────────────

def test_apply_lut_adds_filter_for_valid(tmp_path, monkeypatch):
    f = LUTS_DIR / "warm.cube"
    ed = VideoEditor("/tmp/in.mp4")
    ed.apply_lut("warm.cube")
    assert any("lut3d" in flt for flt in ed.filters)


def test_apply_lut_skips_invalid(tmp_path, monkeypatch):
    bad = tmp_path / "luts"
    bad.mkdir()
    _stub_cube(bad / "broken.cube", size=17, rows=5)
    monkeypatch.setattr("backend.pipeline.video_edit.LUTS_DIR", bad)
    ed = VideoEditor("/tmp/in.mp4")
    ed.apply_lut("broken.cube")
    assert not any("lut3d" in flt for flt in ed.filters)


def test_apply_lut_skips_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.pipeline.video_edit.LUTS_DIR", tmp_path)
    ed = VideoEditor("/tmp/in.mp4")
    ed.apply_lut("doesnotexist.cube")
    assert ed.filters == []


def test_apply_lut_accepts_subpath(tmp_path, monkeypatch):
    """Curated LUTs are passed as a 'cinematic/<name>.cube' subpath, not a flat
    filename — apply_lut must resolve it under LUTS_DIR and add the filter."""
    (tmp_path / "cinematic").mkdir()
    _complete_cube(tmp_path / "cinematic" / "teal_orange.cube", size=2)
    monkeypatch.setattr("backend.pipeline.video_edit.LUTS_DIR", tmp_path)
    ed = VideoEditor("/tmp/in.mp4")
    ed.apply_lut("cinematic/teal_orange.cube")
    assert any("lut3d" in flt for flt in ed.filters)


# ── render fallback ─────────────────────────────────────────────────────────

def test_render_strips_lut3d_on_failure():
    """If the first render fails, render() retries with lut3d stripped."""
    ed = VideoEditor("/tmp/in.mp4")
    ed.filters = ["lut3d='/x/warm.cube'", "cas=strength=0.40"]

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        # Fail while lut3d is present; succeed once it's been stripped.
        has_lut = any("lut3d" in str(part) for part in cmd)
        return MagicMock(returncode=1 if has_lut else 0,
                         stderr=b"Unexpected EOF")

    with patch("backend.pipeline.video_edit.subprocess.run", side_effect=fake_run):
        ok = ed.render("/tmp/out.mp4")

    assert ok is True
    assert not any("lut3d" in flt for flt in ed.filters)
    assert len(calls) >= 2


def test_render_returns_false_when_all_retries_fail():
    ed = VideoEditor("/tmp/in.mp4")
    ed.filters = ["zoompan=z=1", "lut3d='/x/warm.cube'"]
    with patch("backend.pipeline.video_edit.subprocess.run",
               return_value=MagicMock(returncode=1, stderr=b"boom")):
        assert ed.render("/tmp/out.mp4") is False
