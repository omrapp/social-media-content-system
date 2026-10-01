"""Deterministic harness for the merge_clips golden-regression suite.

merge_clips.run() is about to be split into build_plan() + render(plan). Byte
identity of the output MP4 is not provable across FFmpeg builds, so the
load-bearing assertion is:

    the ordered list of subprocess argv invocations is identical
    string-for-string, and the media row handed to upsert_media() is identical.

This module owns everything needed to make that reproducible:

  * seeded RNG (merge_clips shuffles its source plans twice)
  * `merge.cleanup_segments = false` so the scratch dir survives for inspection
  * stubbed `get_track_for_category` / `_music_enter_offset` (both would
    otherwise hit librosa + the on-disk music library), with their call args
    recorded -- that is what protects the `rows`-vs-`cuts` divergence risk,
    since the category/tags/mood passed to music selection never appear in
    any argv
  * stubbed DB surface (no live Supabase/SQLite read anywhere in a golden run)
  * a subprocess wrapper, scoped to the merge modules, that logs argv then
    delegates to the real call (the ffmpeg work really happens)
  * normalization of the two non-deterministic tokens in the captured argv:
    the `mrg_<uuid>` merge id -> `<MERGE_ID>` and the repo root -> `<ROOT>`

Import the fixtures into a test module with:

    from tests.conftest_merge import merge_deterministic, media_row  # noqa: F401
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.fixtures.clips import make_clips

# Seed used for every seeded surface. Do not change -- it invalidates every golden.
SEED = 1234

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "merge_golden"
# Scratch + output for golden runs. Deliberately a sibling of the real MERGE_DIR
# so a capture run can never be confused with (or clobber) a production merge.
# Safe to `rm -rf` at any time; regenerated on the next run.
GOLDEN_WORK = ROOT / "reels_ready" / "merge_golden"

_MERGE_ID_RE = re.compile(r"mrg_[0-9a-f]{12}")

# Stubbed constants. Non-zero enter offset so the `-ss <enter>` branch of the
# delivery command is exercised.
STUB_ENTER_OFFSET = 2.5

# Settings groups merge_clips reads through get_setting(). "merge" is empty so
# _settings() == _DEFAULTS, and each case layers its own overrides via the
# `settings=` kwarg of run().
STUB_SETTINGS: dict[str, dict] = {
    "merge": {},
    "video": {"crf": 20, "preset": "medium"},
    "decaption": {"enabled": False},
    "music": {"mood_match": True},
    "stock": {"enabled": False},
}


# --------------------------------------------------------------------------- #
# Stub media rows
# --------------------------------------------------------------------------- #

def media_row(
    media_id: str,
    clip: str | Path | None = None,
    *,
    category: str = "nature",
    tags: list[str] | None = None,
    source: str = "upload",
    hook_score: float = 0.5,
    quality_score: float = 0.5,
    caption: str = "",
    duration_s: float = 5.0,
) -> dict:
    """A `media` table row shaped like backend/db.py:_MEDIA_COLUMNS, carrying
    only the fields merge_clips actually reads.

    `clip` is a fixture clip NAME (resolved through make_clips) or an explicit
    path. Pass a path that does not exist to model the "resolved source with no
    file on disk" case -- _source_path() returns None for it, so it produces no
    cut while still sitting in `rows` for _first()/_dominant_category()/mood.
    """
    if clip is None:
        local_path = None
    elif isinstance(clip, Path):
        local_path = str(clip)
    else:
        local_path = str(make_clips.clip_path(clip))
    return {
        "id": media_id,
        "source": source,
        "media_type": "VIDEO",
        "status": "raw",
        "local_path": local_path,
        "reel_ready_path": None,
        "decaptioned_path": None,
        "decaptioned": 0,
        "category": category,
        "hook_score": hook_score,
        "quality_score": quality_score,
        "duration_s": duration_s,
        "width": 1080,
        "height": 1920,
        "original_caption": caption,
        "tags": tags or [],
        "do_not_use": 0,
    }


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

def normalize_text(s: str) -> str:
    """Replace the two non-deterministic tokens with stable placeholders."""
    s = s.replace(str(ROOT), "<ROOT>")
    return _MERGE_ID_RE.sub("<MERGE_ID>", s)


def normalize(obj):
    """Recursively normalize strings and round floats (3 dp, matching the
    rounding merge_clips itself applies to cut start/dur/score)."""
    if isinstance(obj, str):
        return normalize_text(obj)
    if isinstance(obj, bool) or obj is None or isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return round(obj, 3)
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalize(v) for v in obj]
    return normalize_text(str(obj))


class _SubprocessShim:
    """Stand-in for the `subprocess` module inside merge_clips: logs argv, then
    delegates every attribute (run, PIPE, CalledProcessError, ...) to the real
    module so behavior is unchanged."""

    def __init__(self, real, log: list):
        self._real = real
        self._log = log

    def __getattr__(self, name):
        return getattr(self._real, name)

    def run(self, args, *a, **kw):
        try:
            argv = [str(x) for x in args]
        except TypeError:  # shell=True string form -- merge_clips never uses it
            argv = [str(args)]
        cwd = kw.get("cwd")
        self._log.append({"argv": argv, "cwd": str(cwd) if cwd else None})
        return self._real.run(args, *a, **kw)


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #

class MergeHarness:
    """Drives one golden case and exposes everything captured from it."""

    def __init__(self, monkeypatch):
        self._mp = monkeypatch
        self.calls: list[dict] = []          # ordered subprocess argv log
        self.upserts: list[dict] = []        # upsert_media() payloads
        self.track_calls: list[dict] = []    # get_track_for_category() call args
        self.enter_calls: list[dict] = []    # _music_enter_offset() call args
        self.pool: list[dict] = []           # auto-select candidate pool
        self.by_id: dict[str, dict] = {}     # get_media_by_id() table
        self.track_result: str | None = None  # what get_track_for_category returns
        self.result: dict | None = None      # run() return value

    # -- pool / row wiring ------------------------------------------------- #

    def set_pool(self, rows: list[dict]) -> None:
        """Rows visible to get_category_raw_media (auto-select)."""
        self.pool = [dict(r) for r in rows]
        for r in self.pool:
            self.by_id[r["id"]] = dict(r)

    def register(self, rows: list[dict]) -> None:
        """Rows visible to get_media_by_id (hand-pick)."""
        for r in rows:
            self.by_id[r["id"]] = dict(r)

    # -- execution --------------------------------------------------------- #

    def run_case(self, case: str, settings: dict | None = None, **run_kwargs) -> dict:
        """Run merge_clips.run() for one golden case under a per-case MERGE_DIR.

        Every seeded/stubbed surface is reset first, so cases are independent of
        collection order.
        """
        from backend.pipeline import merge_clips as mc

        work = GOLDEN_WORK / case
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        self._mp.setattr(mc, "MERGE_DIR", work)

        self.calls.clear()
        self.upserts.clear()
        self.track_calls.clear()
        self.enter_calls.clear()

        # Reset both RNG surfaces per case: the module-level `random` (seeded)
        # and the dedicated Random instance backing the patched shuffle.
        random.seed(SEED)
        self._rng.seed(SEED)

        cfg = dict(settings or {})
        # Keep the scratch segments on disk for inspection -- and so a failing
        # diff can be traced back to the exact intermediate files.
        cfg["cleanup_segments"] = False

        self.result = mc.run(settings=cfg, **run_kwargs)
        return self.result

    # -- capture ----------------------------------------------------------- #

    def argv_payload(self) -> list[dict]:
        return normalize(self.calls)

    def meta_payload(self) -> dict:
        """Everything that is NOT an argv but must still be byte-stable across
        the refactor: the run() return dict, the full media row written by
        upsert_media (metadata.merge included), and the arguments handed to the
        stubbed music helpers."""
        return normalize({
            "result": self.result,
            "upserts": self.upserts,
            "track_calls": self.track_calls,
            "enter_calls": self.enter_calls,
        })


@pytest.fixture
def merge_deterministic(monkeypatch):
    """Every non-deterministic surface in merge_clips pinned. Yields a
    MergeHarness."""
    from backend.pipeline import merge_clips as mc
    import backend.db as db
    from backend.pipeline import music_fetcher

    make_clips.ensure_clips()
    make_clips.ensure_music()
    GOLDEN_WORK.mkdir(parents=True, exist_ok=True)

    h = MergeHarness(monkeypatch)
    h._rng = random.Random(SEED)

    # 1. RNG. merge_clips shuffles the source plans (:1188) and the loop block in
    #    the min-duration guarantee (:1336). Both go through merge_clips.random.
    random.seed(SEED)
    monkeypatch.setattr(mc.random, "shuffle", h._rng.shuffle)

    # 2. Music helpers -> constants, with call args recorded. get_track_for_category
    #    is a LATE import inside build_plan()/render(), so the patch has to land on
    #    the source module; the merge_clips-namespace patch is forward-compat for
    #    the refactor hoisting it to a module-level import.
    def _fake_track(category, tags=None, avoid_ids=None, clip_len=None,
                    mood=None, avoid_names=None):
        h.track_calls.append({
            "category": category, "tags": tags, "clip_len": clip_len,
            "mood": mood, "avoid_ids": avoid_ids, "avoid_names": avoid_names,
        })
        return h.track_result

    monkeypatch.setattr(music_fetcher, "get_track_for_category", _fake_track)
    monkeypatch.setattr(mc, "get_track_for_category", _fake_track, raising=False)

    def _fake_enter(track_path, seg_len):
        h.enter_calls.append({"track": Path(str(track_path)).name,
                              "seg_len": round(float(seg_len), 3)})
        return STUB_ENTER_OFFSET

    monkeypatch.setattr(mc, "_music_enter_offset", _fake_enter)

    # 3. subprocess -> logging shim, scoped to the merge modules only. The list
    #    of module names is deliberately forgiving so the post-refactor split
    #    (merge_plan / merge_render) is picked up without editing this fixture.
    shim = _SubprocessShim(subprocess, h.calls)
    monkeypatch.setattr(mc, "subprocess", shim)
    for extra in ("backend.pipeline.merge_plan", "backend.pipeline.merge_render"):
        try:
            mod = __import__(extra, fromlist=["*"])
        except Exception:
            continue
        if hasattr(mod, "subprocess"):
            monkeypatch.setattr(mod, "subprocess", shim)

    # 4. DB surface. Nothing in a golden run may touch a real database.
    monkeypatch.setattr(mc, "upsert_media", lambda data: h.upserts.append(data))
    monkeypatch.setattr(mc, "update_media", lambda mid, data: None)
    monkeypatch.setattr(mc, "get_media_by_id",
                        lambda mid: dict(h.by_id[mid]) if mid in h.by_id else None)
    monkeypatch.setattr(mc, "get_setting",
                        lambda key, default=None: dict(STUB_SETTINGS.get(key, {})))

    def _fake_category_pool(category, exclude_ids, tags=None,
                            strategy="random", source=None):
        """First match wins -- no random.choice, unlike the real picker, so the
        selection order is a pure function of the fixture pool.

        `tags` (when given) is an optional secondary filter: at least one
        requested tag must be present on the row's own tags list. None of the
        15 golden cases pass a top-level `tags` to run(), so this branch is
        currently unexercised but kept for signature fidelity with
        db.get_category_raw_media."""
        for r in h.pool:
            if r["id"] in (exclude_ids or []):
                continue
            if category and r.get("category") != category:
                continue
            if tags and not (set(tags) & set(r.get("tags") or [])):
                continue
            if source == "stock" and r.get("source") != "stock":
                continue
            if source == "local" and r.get("source") == "stock":
                continue
            return dict(r)
        return None

    monkeypatch.setattr(db, "get_category_raw_media", _fake_category_pool)
    monkeypatch.setattr(db, "get_recent_merge_usage",
                        lambda category, limit_reels=3: ({}, []))

    # 5. Music containment dir -> fixture bed, so _safe_music_path() resolves an
    #    explicit music_path without depending on the user's assets/music/.
    monkeypatch.setattr(mc, "MUSIC_DIR", make_clips.MUSIC_DIR)

    yield h


# --------------------------------------------------------------------------- #
# Golden IO
# --------------------------------------------------------------------------- #

def golden_paths(case: str) -> tuple[Path, Path]:
    return GOLDEN_DIR / f"{case}.argv.json", GOLDEN_DIR / f"{case}.meta.json"


def write_golden(case: str, argv_payload, meta_payload) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    argv_p, meta_p = golden_paths(case)
    argv_p.write_text(json.dumps(argv_payload, indent=2, sort_keys=False) + "\n")
    meta_p.write_text(json.dumps(meta_payload, indent=2, sort_keys=False) + "\n")


def read_golden(case: str) -> tuple[list, dict]:
    argv_p, meta_p = golden_paths(case)
    if not argv_p.exists() or not meta_p.exists():
        pytest.fail(
            f"no golden fixture for case '{case}'.\n"
            f"  expected: {argv_p}\n"
            f"            {meta_p}\n"
            f"  capture it at PRE-REFACTOR HEAD with:\n"
            f"    MERGE_GOLDEN=capture pytest tests/test_merge_golden.py -m slow -k {case}"
        )
    return json.loads(argv_p.read_text()), json.loads(meta_p.read_text())


def diff_argv(case: str, expected: list, actual: list) -> str:
    """A readable report of the FIRST differing invocation, plus both lists."""
    lines = [f"argv mismatch for golden case '{case}'"]
    if len(expected) != len(actual):
        lines.append(f"  invocation COUNT differs: expected {len(expected)}, got {len(actual)}")
    idx = None
    for i in range(min(len(expected), len(actual))):
        if expected[i] != actual[i]:
            idx = i
            break
    if idx is None and len(expected) != len(actual):
        idx = min(len(expected), len(actual))
    if idx is not None:
        lines.append(f"  first difference at invocation index {idx}:")
        exp = expected[idx] if idx < len(expected) else "<missing>"
        act = actual[idx] if idx < len(actual) else "<missing>"
        lines.append(f"    expected: {json.dumps(exp)}")
        lines.append(f"    actual:   {json.dumps(act)}")
        if isinstance(exp, dict) and isinstance(act, dict):
            ea, aa = exp.get("argv", []), act.get("argv", [])
            for j in range(max(len(ea), len(aa))):
                e = ea[j] if j < len(ea) else "<missing>"
                a = aa[j] if j < len(aa) else "<missing>"
                if e != a:
                    lines.append(f"      first differing token [{j}]:")
                    lines.append(f"        expected: {e!r}")
                    lines.append(f"        actual:   {a!r}")
                    break
    lines.append("  --- full expected argv list ---")
    lines.append(json.dumps(expected, indent=2))
    lines.append("  --- full actual argv list ---")
    lines.append(json.dumps(actual, indent=2))
    return "\n".join(lines)
