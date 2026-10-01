"""Convert every .cube 3D LUT into a 2D LUT strip PNG for the editor preview.

The editor previews colour in the browser with a WebGL shader; WebGL1 has no
3D textures, so each `.cube` is baked into the conventional 2D strip layout:

    width  = size * size      (one square tile per BLUE slice, left to right)
    height = size             (x within a tile = RED, y = GREEN)

Run it once after adding LUTs (it is pure CPU and takes seconds — hence a
script, not a request-time conversion):

    python -m backend.scripts.make_lut_previews            # only missing/stale
    python -m backend.scripts.make_lut_previews --force    # rebuild everything

Output goes to `assets/luts/_preview/`, which the existing `/static/assets`
mount already serves. Names are the LUT's LUTS_DIR-relative path with `/`
replaced by `__` ("cinematic/teal_orange.cube" -> "cinematic__teal_orange.png")
so the whole tree flattens without collisions.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import LUTS_DIR  # noqa: E402

log = logging.getLogger("make_lut_previews")

PREVIEW_DIRNAME = "_preview"
# Anything larger is a pathological .cube — a 64³ LUT is already a 4096x64 PNG.
MAX_SIZE = 64


def preview_name(rel: str) -> str:
    """LUTS_DIR-relative .cube path -> flat PNG filename."""
    return rel.replace("\\", "/").replace("/", "__").rsplit(".", 1)[0] + ".png"


def parse_cube(path: Path) -> tuple[int, list[tuple[float, float, float]]]:
    """Minimal .cube parser: LUT_3D_SIZE + the RGB triplet table.

    Returns (size, entries) with entries in the file's own order — red varies
    fastest, then green, then blue, which is what the .cube spec mandates.
    """
    size = 0
    dom_min = [0.0, 0.0, 0.0]
    dom_max = [1.0, 1.0, 1.0]
    entries: list[tuple[float, float, float]] = []

    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split()[0].upper()
        if head == "LUT_3D_SIZE":
            size = int(line.split()[1])
            continue
        if head == "DOMAIN_MIN":
            dom_min = [float(x) for x in line.split()[1:4]]
            continue
        if head == "DOMAIN_MAX":
            dom_max = [float(x) for x in line.split()[1:4]]
            continue
        if head in ("TITLE", "LUT_1D_SIZE", "LUT_IN_VIDEO_RANGE"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            entries.append((float(parts[0]), float(parts[1]), float(parts[2])))
        except ValueError:
            continue

    if size <= 0:
        raise ValueError("missing LUT_3D_SIZE")
    if size > MAX_SIZE:
        raise ValueError(f"LUT_3D_SIZE {size} exceeds the {MAX_SIZE} cap")
    if len(entries) != size ** 3:
        raise ValueError(f"expected {size ** 3} entries, found {len(entries)}")

    # Normalise a non-0..1 domain so the shader can always sample in 0..1.
    span = [(hi - lo) or 1.0 for lo, hi in zip(dom_min, dom_max)]
    if dom_min != [0.0, 0.0, 0.0] or dom_max != [1.0, 1.0, 1.0]:
        entries = [
            tuple((v - lo) / s for v, lo, s in zip(px, dom_min, span))  # type: ignore[misc]
            for px in entries
        ]
    return size, entries


def build_png(size: int, entries, out_path: Path) -> None:
    import numpy as np
    from PIL import Image

    arr = np.asarray(entries, dtype=np.float32).reshape(size, size, size, 3)  # [b][g][r]
    # -> row-major image rows (green) x columns (blue-tile, red)
    img = arr.transpose(1, 0, 2, 3).reshape(size, size * size, 3)
    img = np.clip(img, 0.0, 1.0) * 255.0 + 0.5
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img.astype(np.uint8), mode="RGB").save(out_path, optimize=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="rebuild PNGs that already exist")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    root = Path(LUTS_DIR)
    if not root.exists():
        log.error("LUT dir not found: %s", root)
        return 1
    out_dir = root / PREVIEW_DIRNAME

    cubes = sorted(p for p in root.rglob("*.cube") if PREVIEW_DIRNAME not in p.parts)
    if not cubes:
        log.info("no .cube files under %s", root)
        return 0

    made = skipped = failed = 0
    for cube in cubes:
        rel = str(cube.relative_to(root))
        out = out_dir / preview_name(rel)
        if out.exists() and not args.force and out.stat().st_mtime >= cube.stat().st_mtime:
            skipped += 1
            continue
        try:
            size, entries = parse_cube(cube)
            build_png(size, entries, out)
            log.info("  %s -> %s (%d³)", rel, out.name, size)
            made += 1
        except Exception as exc:
            log.warning("  SKIP %s — %s", rel, exc)
            failed += 1

    log.info("%d written, %d up to date, %d failed -> %s", made, skipped, failed, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
