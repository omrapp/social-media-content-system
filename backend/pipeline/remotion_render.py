"""
Python wrapper for Remotion CLI rendering.
Renders compositions with JSON props passed via --props flag.

Usage:
    python -m backend.pipeline.remotion_render --media-id abc123
    python -m backend.pipeline.remotion_render --composition HiddenGemReel --props '{"tags":"Tokyo, night market"}'
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from backend.config import ROOT_DIR, REELS_READY_DIR
from backend.db import get_media_by_id, update_media, update_status

REMOTION_DIR = ROOT_DIR / "remotion"

CATEGORY_COMPOSITION = {
    "hidden_gem": "HiddenGemReel",
    "budget": "BudgetReel",
    "culture": "CultureReel",
    "nature": "NatureReel",
    "food": "FoodReel",
    "beach": "BeachReel",
}


def render_composition(composition: str, props: dict, output_path: str, timeout=300) -> dict:
    if not (REMOTION_DIR / "node_modules").exists():
        return {"status": "error", "reason": "remotion not installed — run: cd remotion && npm install"}

    props_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(props, props_file)
    props_file.close()

    cmd = [
        "npx", "remotion", "render",
        composition,
        output_path,
        "--props", props_file.name,
        "--codec", "h264",
        "--crf", "22",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(REMOTION_DIR), timeout=timeout,
        )
        Path(props_file.name).unlink(missing_ok=True)

        if result.returncode == 0:
            return {"status": "rendered", "output": output_path}
        return {"status": "error", "reason": result.stderr[-500:] if result.stderr else "unknown"}
    except subprocess.TimeoutExpired:
        Path(props_file.name).unlink(missing_ok=True)
        return {"status": "error", "reason": "render_timeout"}


def render_for_media(media_id: str) -> dict:
    item = get_media_by_id(media_id)
    if not item:
        return {"status": "error", "reason": "media_not_found"}

    category = item.get("category", "hidden_gem")
    composition = CATEGORY_COMPOSITION.get(category, "HiddenGemReel")

    tags = item.get("tags") or []
    props = {
        "mediaId": media_id,
        "videoUrl": item.get("r2_url") or item.get("reel_ready_path", ""),
        "tags": ", ".join(tags) if isinstance(tags, list) else (tags or ""),
        "caption": item.get("caption", ""),
        "category": category,
        "hookText": (item.get("caption") or "")[:50],
    }

    output_path = str(REELS_READY_DIR / f"{media_id}_remotion.mp4")
    result = render_composition(composition, props, output_path)

    if result["status"] == "rendered":
        update_media(media_id, {"reel_ready_path": output_path, "status": "edited"})
    else:
        update_status(media_id, "error", result.get("reason"))

    return result


def run(media_id=None, composition=None, props=None):
    if not (REMOTION_DIR / "node_modules").exists():
        return {"skipped": True, "reason": "remotion_not_installed — run: cd remotion && npm install"}

    if media_id:
        return render_for_media(media_id)

    if composition and props:
        output = str(REELS_READY_DIR / f"{composition}_output.mp4")
        return render_composition(composition, props, output)

    items = []
    try:
        from backend.db import get_media
        items = get_media(filters={"status": "resized"})
    except Exception:
        pass

    if not items:
        return {"rendered": 0, "total": 0}

    rendered = 0
    for item in items:
        result = render_for_media(item["id"])
        if result["status"] == "rendered":
            rendered += 1
    return {"rendered": rendered, "total": len(items)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-id", help="Render for specific media")
    parser.add_argument("--composition", help="Composition name")
    parser.add_argument("--props", help="JSON props string")
    args = parser.parse_args()

    props = json.loads(args.props) if args.props else None
    result = run(media_id=args.media_id, composition=args.composition, props=props)
    print(result)
