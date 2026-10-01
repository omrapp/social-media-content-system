"""
Curate raw vendor .cube LUTs into the cinematic library.  ── MANUAL, CPU-HEAVY ──

This is a USER-RUN script (it is intentionally NOT called by the pipeline or any
agent). It walks the raw vendor downloads in assets/cubes/, drops structurally
invalid / truncated .cube files (via valid_cube), copies a curated keep-list into
assets/luts/cinematic/ with normalized snake_case names, and emits the catalog
(assets/luts/catalog.json) that drives content-aware LUT selection.

Usage:
    # 1. See what would be kept/dropped (no writes):
    python -m backend.scripts.curate_luts --dry-run

    # 2. Actually copy keepers + write catalog.json:
    python -m backend.scripts.curate_luts --apply

    # 3. (Optional, slow) FFmpeg-smoke-test every keeper before copying:
    python -m backend.scripts.curate_luts --apply --ffmpeg-test

After running, review assets/luts/catalog.json, then commit the new
assets/luts/cinematic/*.cube + catalog.json and move them to the server.

The RECOMMENDED keep-list below maps vendor-filename substrings → catalog
metadata (name, mood/topic tags using the music_mood vocabulary, pillars). Tags
drive `mood` selection; pillars drive the deterministic fallback. Edit it to taste
— anything not matched is reported and skipped unless --keep-all is passed.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from backend.config import CUBES_STAGING_DIR, LUTS_CINEMATIC_DIR, LUT_CATALOG_PATH, LUTS_DIR
from backend.pipeline.video_edit import valid_cube

# mood vocabulary (must match backend/pipeline/music_mood.py MOOD_TAGS keys):
#   adventurous · calm · romantic · fun · epic · reflective
# pillars: hidden_gem · budget · culture · nature · food · beach
#
# CURATION STRATEGY (3 tiers, in order):
#   1. EXCLUDE_LOG — drop Log-input technical conversion LUTs (Arrakis/Bat/Cliff/
#      Gems/Guardians/Licorice/Parasitic with -CLog/-DLog/-FLog/-LogC4/-NLog/-SLog/
#      -VLog suffixes). They expect raw Log footage; on already-graded IG clips they
#      crush/oversaturate. ~77 files. Override with --keep-log.
#   2. RECOMMENDED — explicit overrides for marquee looks (name/tags/pillars).
#      key = case-insensitive substring matched against the filename.
#   3. AUTO — every other valid, non-Log creative LUT is KEPT, its display name
#      derived from the filename and its tags/pillars inferred from KEYWORD_RULES.
#      This is what pulls in the full fixthephoto (ftp_*) + IWLTBAP + PB_ libraries.

RECOMMENDED: dict[str, dict] = {
    "twilight":      {"name": "Twilight",        "tags": ["romantic", "calm"],       "pillars": ["beach", "hidden_gem"]},
    "frosty":        {"name": "Frosty",          "tags": ["calm", "reflective"],     "pillars": ["nature"]},
    "cool mist":     {"name": "Cool Mist",       "tags": ["calm", "reflective"],     "pillars": ["nature", "budget"]},
    "pastel film":   {"name": "Pastel Film",     "tags": ["romantic", "fun"],        "pillars": ["culture", "food"]},
    "skyscraper":    {"name": "Skyscraper",      "tags": ["epic"],                   "pillars": ["culture", "budget"]},
    "orange & teal": {"name": "Teal & Orange",   "tags": ["epic", "adventurous"],    "pillars": ["nature", "beach", "hidden_gem"]},
    "orangeandblue": {"name": "Orange & Blue",   "tags": ["epic", "adventurous"],    "pillars": ["nature", "beach"]},
    "magichour":     {"name": "Magic Hour",      "tags": ["romantic", "calm"],       "pillars": ["food", "beach"]},
    "bluehour":      {"name": "Blue Hour",       "tags": ["calm", "reflective"],     "pillars": ["nature", "hidden_gem"]},
    "lushgreen":     {"name": "Lush Green",      "tags": ["calm", "adventurous"],    "pillars": ["nature"]},
}

# Log-input technical LUTs — drop unless --keep-log. Matched on lowercased stem.
EXCLUDE_LOG = re.compile(r"-(c|d|f|n|s|v)log\d?$|-logc4$")

# Ordered keyword → (tags, pillars). Scanned against the lowercased filename;
# every rule that hits contributes; tags capped 2, pillars capped 3. First rule
# also sets the primary so order = priority. Vocabulary above.
KEYWORD_RULES: list[tuple[str, list[str], list[str]]] = [
    (r"warm|golden|sunset|twilight|amber|orange|dusty|wheat|beige|bourbon|sand|magic|morning|glow|sunrise",
        ["romantic", "calm"], ["food", "beach"]),
    (r"cool|cold|mist|frost|frosty|blue|noir|somber|dark|night|chrome|ice|chill|shade|midlight|violet|purple|magenta|turquoise|sea|loch|wave|water|reflection",
        ["calm", "reflective"], ["nature", "beach"]),
    (r"pastel|soft|fade|faded|film|vintage|retro|antique|matte|tint|tinted|nostalg|emulation|frame|cross process",
        ["reflective", "romantic"], ["culture", "food"]),
    (r"contrast|dramatic|hard|boost|vibran|sharp|neon|pop|bright|deep|dimension|evolution|shine|enchant|cinematic|teal",
        ["epic", "adventurous"], ["hidden_gem", "nature"]),
    (r"green|foliage|lush|forest|harmony|landscape|aerial|drone|sky|mountain|autumn|natural|tropic|space",
        ["adventurous", "calm"], ["nature"]),
    (r"city|urban|skyscraper|architecture|street|prague|oslo|reykjavik|seattle|phoenix",
        ["epic"], ["culture", "budget"]),
    (r"b&w|black|mono|noir|w&b",
        ["reflective"], ["culture"]),
]
DEFAULT_TAGS = ["reflective", "calm"]
DEFAULT_PILLARS = ["culture", "hidden_gem"]


def walk_cubes(cubes_dir: Path) -> list[Path]:
    return sorted(p for p in cubes_dir.rglob("*.cube") if p.is_file())


def normalize_name(meta_name: str) -> str:
    """Catalog display name → snake_case .cube filename."""
    s = re.sub(r"[^a-z0-9]+", "_", meta_name.lower()).strip("_")
    return f"{s}.cube"


def is_log_lut(path: Path) -> bool:
    """True for Log-input technical conversion LUTs (not creative looks)."""
    return bool(EXCLUDE_LOG.search(path.stem.lower()))


def derive_name(path: Path) -> str:
    """Human display name from a vendor filename.

    Strips fixthephoto download prefixes, leading index numbers, and the
    '<Vendor> LUTs_' segment, keeping the descriptive tail. PB_ location series
    keeps the location word.
        'ftp_ground_control_luts_download_1_01_Ground Control LUTs_Twilight' → 'Twilight'
        '01_Dji LUTs_Aerial Sky' → 'Aerial Sky'
        'PB_Tahoe' → 'PB Tahoe'   ·   'Bourbon 64' → 'Bourbon 64'
    """
    s = path.stem
    if "LUTs_" in s:                     # vendor/ftp pattern: keep tail look name
        s = s.rsplit("LUTs_", 1)[1]
    else:
        s = re.sub(r"^ftp_.*?_\d+_\d+_", "", s)   # any residual ftp prefix
        s = re.sub(r"^\d+_", "", s)               # leading NN_
    s = re.sub(r"[_]+", " ", s).strip()
    return s or path.stem


def auto_meta(path: Path) -> dict:
    """Derive catalog metadata for an unmapped creative LUT from its filename."""
    hay = path.name.lower()
    tags: list[str] = []
    pillars: list[str] = []
    for pattern, t, p in KEYWORD_RULES:
        if re.search(pattern, hay):
            tags += t
            pillars += p
    # dedupe preserving order, cap
    tags = list(dict.fromkeys(tags or DEFAULT_TAGS))[:2]
    pillars = list(dict.fromkeys(pillars or DEFAULT_PILLARS))[:3]
    return {"name": derive_name(path), "tags": tags, "pillars": pillars}


def match_meta(path: Path) -> dict | None:
    """Explicit RECOMMENDED override (substring) → else auto-derived metadata.
    Returns None only for Log LUTs (filtered earlier) — every creative look maps."""
    name = path.name.lower()
    for key, meta in RECOMMENDED.items():
        if key in name:
            return meta
    return auto_meta(path)


def ffmpeg_ok(cube: Path) -> bool:
    """Apply the LUT to a 1-frame test pattern — catches files that pass the row
    count but still choke ffmpeg. Slow: one ffmpeg invocation per file."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", "testsrc=size=64x64:duration=0.1:rate=1",
             "-vf", f"lut3d='{cube}'", "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, timeout=60,
        )
        return r.returncode == 0
    except Exception:
        return False


def curate(cubes_dir: Path, out_dir: Path, catalog_path: Path,
           apply: bool = False, ffmpeg_test: bool = False,
           keep_all: bool = False, keep_log: bool = False) -> dict:
    found = walk_cubes(cubes_dir)
    kept: list[dict] = []
    dropped: list[tuple[str, str]] = []
    used_names: set[str] = set()

    print(f"Scanning {cubes_dir} … found {len(found)} .cube files\n")

    for path in found:
        if not valid_cube(path):
            dropped.append((path.name, "invalid/truncated cube"))
            continue
        if is_log_lut(path) and not (keep_log or keep_all):
            dropped.append((path.name, "Log-input technical LUT (use --keep-log)"))
            continue
        meta = match_meta(path)
        if meta is None and not keep_all:
            dropped.append((path.name, "no keep-list match"))
            continue
        if ffmpeg_test and not ffmpeg_ok(path):
            dropped.append((path.name, "ffmpeg lut3d test failed"))
            continue

        meta = meta or {"name": path.stem, "tags": [], "pillars": []}
        out_name = normalize_name(meta["name"])
        # de-dupe collisions (two vendor files → same look name)
        base = out_name
        i = 2
        while out_name in used_names:
            out_name = base.replace(".cube", f"_{i}.cube")
            i += 1
        used_names.add(out_name)

        kept.append({
            "file": f"cinematic/{out_name}",
            "name": meta["name"],
            "tags": meta.get("tags", []),
            "categories": meta.get("pillars", []),
            "intensity": meta.get("intensity", 0.85),
            "source": path.relative_to(cubes_dir).parts[0] if path.relative_to(cubes_dir).parts else "",
            "_src": str(path),
        })

    print(f"KEEP ({len(kept)}):")
    for e in kept:
        print(f"  {e['file']:<34} tags={e['tags']} categories={e['pillars']}  ← {Path(e['_src']).name}")
    print(f"\nDROP ({len(dropped)}):")
    for name, why in dropped:
        print(f"  {name:<44} {why}")

    if not apply:
        print("\n[dry-run] nothing written. Re-run with --apply to copy + write catalog.")
        return {"kept": len(kept), "dropped": len(dropped), "applied": False}

    out_dir.mkdir(parents=True, exist_ok=True)
    catalog_entries: list[dict] = []
    for e in kept:
        shutil.copy2(e["_src"], LUTS_DIR / e["file"])
        catalog_entries.append({k: v for k, v in e.items() if not k.startswith("_")})

    catalog_path.write_text(json.dumps({"version": 1, "luts": catalog_entries}, indent=2) + "\n")
    print(f"\n[applied] copied {len(kept)} LUTs → {out_dir}")
    print(f"[applied] wrote catalog → {catalog_path}")
    return {"kept": len(kept), "dropped": len(dropped), "applied": True}


def main() -> int:
    ap = argparse.ArgumentParser(description="Curate vendor .cube LUTs into the cinematic library.")
    ap.add_argument("--cubes-dir", type=Path, default=CUBES_STAGING_DIR)
    ap.add_argument("--out-dir", type=Path, default=LUTS_CINEMATIC_DIR)
    ap.add_argument("--catalog", type=Path, default=LUT_CATALOG_PATH)
    ap.add_argument("--dry-run", action="store_true", help="(default) preview only — no writes")
    ap.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    ap.add_argument("--ffmpeg-test", action="store_true", help="smoke-test each keeper with ffmpeg (slow)")
    ap.add_argument("--keep-all", action="store_true", help="keep every valid cube, incl. Log LUTs")
    ap.add_argument("--keep-log", action="store_true", help="also keep Log-input technical LUTs (off by default)")
    args = ap.parse_args()

    if not args.cubes_dir.exists():
        print(f"error: cubes dir not found: {args.cubes_dir}", file=sys.stderr)
        return 1
    curate(args.cubes_dir, args.out_dir, args.catalog,
           apply=args.apply, ffmpeg_test=args.ffmpeg_test,
           keep_all=args.keep_all, keep_log=args.keep_log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
