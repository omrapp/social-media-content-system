"""
Content-aware LUT selection tests (lut_select.select_lut cascade).

Pins the invariants: the cascade honours mode (fixed/mood/category/vision), always
degrades to the legacy CATEGORY_LUT floor, never invokes vision unless enabled, is
path-traversal safe, and never raises into the edit stage.
"""
import json

import pytest

from backend.pipeline import lut_select
from backend.pipeline.video_edit import CATEGORY_LUT


def _cube(path, size=2):
    rows = ["LUT_3D_SIZE %d" % size, ""]
    rows += ["0.5 0.5 0.5"] * (size ** 3)
    path.write_text("\n".join(rows) + "\n")


@pytest.fixture
def lut_env(tmp_path, monkeypatch):
    """A tmp LUTS_DIR with a cinematic/ subdir and catalog.json wired into
    lut_select. Returns a helper that writes a catalog + the backing .cube files."""
    cinematic = tmp_path / "cinematic"
    cinematic.mkdir()
    catalog_path = tmp_path / "catalog.json"
    monkeypatch.setattr(lut_select, "LUTS_DIR", tmp_path)
    monkeypatch.setattr(lut_select, "LUT_CATALOG_PATH", catalog_path)
    lut_select._reset_cache()

    def write_catalog(entries):
        for e in entries:
            _cube(tmp_path / e["file"])
        catalog_path.write_text(json.dumps({"version": 1, "luts": entries}))
        lut_select._reset_cache()

    yield tmp_path, write_catalog
    lut_select._reset_cache()


def test_load_catalog_empty_when_missing(lut_env):
    assert lut_select.load_catalog() == []


def test_load_catalog_filters_missing_files(lut_env):
    _, write_catalog = lut_env
    write_catalog([{"file": "cinematic/present.cube", "tags": ["epic"], "categories": []}])
    # add a phantom entry whose file was never created
    cat = json.loads((lut_select.LUT_CATALOG_PATH).read_text())
    cat["luts"].append({"file": "cinematic/ghost.cube", "tags": [], "categories": []})
    lut_select.LUT_CATALOG_PATH.write_text(json.dumps(cat))
    lut_select._reset_cache()
    files = [e["file"] for e in lut_select.load_catalog()]
    assert "cinematic/present.cube" in files
    assert "cinematic/ghost.cube" not in files


def test_corrupt_catalog_never_raises(lut_env):
    lut_select.LUT_CATALOG_PATH.write_text("{not valid json")
    lut_select._reset_cache()
    assert lut_select.load_catalog() == []


def test_fixed_mode_returns_fixed_lut(lut_env):
    tmp_path, _ = lut_env
    _cube(tmp_path / "cinematic" / "chosen.cube")
    out = lut_select.select_lut(
        {"category": "food"},
        settings={"lut_mode": "fixed", "fixed_lut": "cinematic/chosen.cube"},
    )
    assert out == "cinematic/chosen.cube"


def test_fixed_mode_missing_file_falls_back_to_category(lut_env):
    out = lut_select.select_lut(
        {"category": "food"},
        settings={"lut_mode": "fixed", "fixed_lut": "cinematic/gone.cube"},
    )
    assert out == CATEGORY_LUT["food"]


def test_mood_mode_picks_mood_tagged_entry(lut_env, monkeypatch):
    _, write_catalog = lut_env
    write_catalog([{"file": "cinematic/epic_look.cube", "tags": ["epic"], "categories": []}])
    monkeypatch.setattr(lut_select, "mood_from_text", lambda *a, **k: "epic")
    out = lut_select.select_lut(
        {"category": "nature", "original_caption": "breathtaking"},
        settings={"lut_mode": "mood"},
    )
    assert out == "cinematic/epic_look.cube"


def test_category_mode_falls_back_to_legacy_map(lut_env, monkeypatch):
    # Empty catalog + no mood hit → legacy CATEGORY_LUT floor.
    monkeypatch.setattr(lut_select, "mood_from_text", lambda *a, **k: None)
    out = lut_select.select_lut({"category": "culture"}, settings={"lut_mode": "category"})
    assert out == CATEGORY_LUT["culture"]


def test_catalog_category_match_preferred_over_legacy(lut_env, monkeypatch):
    _, write_catalog = lut_env
    write_catalog([{"file": "cinematic/nature_look.cube", "tags": [], "categories": ["nature"]}])
    monkeypatch.setattr(lut_select, "mood_from_text", lambda *a, **k: None)
    out = lut_select.select_lut({"category": "nature"}, settings={"lut_mode": "category"})
    assert out == "cinematic/nature_look.cube"


def test_vision_not_called_when_disabled(lut_env, monkeypatch):
    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return None

    monkeypatch.setattr(lut_select, "_vision_lut", spy)
    monkeypatch.setattr(lut_select, "mood_from_text", lambda *a, **k: None)
    lut_select.select_lut({"category": "food"}, settings={"lut_mode": "category", "use_vision": False})
    assert called["n"] == 0


def test_vision_called_when_enabled(lut_env, monkeypatch):
    _, write_catalog = lut_env
    write_catalog([{"file": "cinematic/v.cube", "tags": [], "categories": ["beach"]}])
    monkeypatch.setattr(lut_select, "_vision_lut", lambda item, cat: "cinematic/v.cube")
    out = lut_select.select_lut({"category": "food"}, settings={"lut_mode": "mood", "use_vision": True})
    assert out == "cinematic/v.cube"


def test_vision_uses_cached_metadata_category(lut_env, monkeypatch):
    _, write_catalog = lut_env
    write_catalog([{"file": "cinematic/beach_look.cube", "tags": [], "categories": ["beach"]}])
    # classify must NOT be called when metadata.vision.category is present.
    def boom(*a, **k):
        raise AssertionError("classify_frames should not run when vision category is cached")
    monkeypatch.setattr("backend.pipeline.classify_vision.classify_frames", boom)
    item = {"category": "food", "metadata": {"vision": {"category": "beach"}}}
    out = lut_select.select_lut(item, settings={"lut_mode": "vision", "use_vision": True})
    assert out == "cinematic/beach_look.cube"


def test_classify_failure_never_raises(lut_env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("groq down")
    monkeypatch.setattr("backend.pipeline.classify_vision.classify_frames", boom)
    monkeypatch.setattr(lut_select, "mood_from_text", lambda *a, **k: None)
    # no cached vision category, no reel file → _vision_lut returns None, cascade continues
    out = lut_select.select_lut(
        {"category": "budget", "metadata": {}},
        settings={"lut_mode": "vision", "use_vision": True},
    )
    assert out == CATEGORY_LUT["budget"]


def test_override_wins(lut_env):
    tmp_path, _ = lut_env
    _cube(tmp_path / "cinematic" / "manual.cube")
    out = lut_select.select_lut(
        {"category": "food"},
        settings={"lut_mode": "category"},
        override="cinematic/manual.cube",
    )
    assert out == "cinematic/manual.cube"


def test_override_traversal_rejected(lut_env):
    out = lut_select.select_lut(
        {"category": "food"},
        settings={"lut_mode": "category"},
        override="../../etc/passwd",
    )
    # rejected → falls through to category floor, never returns the traversal path
    assert out == CATEGORY_LUT["food"]


def test_safe_lut_rejects_traversal(lut_env):
    assert lut_select._safe_lut("../../etc/passwd") is None


def test_select_lut_never_raises_on_bad_input(lut_env):
    # missing category, weird types — must not raise.
    assert lut_select.select_lut({}, settings={}) is None or True
