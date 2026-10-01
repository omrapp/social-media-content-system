import re
import json
import requests

from backend.config import IG_TOKEN, IG_USER_ID, IG_API_BASE, ORGANIZED_DIR, HIGHLIGHTS_MANIFEST
from backend.pipeline.audio_probe import probe as audio_probe

UNCATEGORIZED_HIGHLIGHTS_DIR = ORGANIZED_DIR / "uncategorized" / "highlights"


def safe_name(s):
    return re.sub(r"[^\w\-]", "_", s)


def download_file(url, dest):
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, stream=True)
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)


def run(highlight_filter=None):
    r = requests.get(
        f"{IG_API_BASE}/{IG_USER_ID}/highlights",
        params={"fields": "id,title,cover_media", "access_token": IG_TOKEN}
    ).json()
    highlights = r.get("data", [])

    existing_manifest = {}
    if HIGHLIGHTS_MANIFEST.exists():
        existing_manifest = json.loads(HIGHLIGHTS_MANIFEST.read_text())

    existing_ids = set()
    for data in existing_manifest.values():
        for item in data.get("items", []):
            existing_ids.add(item["id"])

    manifest = dict(existing_manifest)
    downloaded = 0
    skipped = 0

    for hl in highlights:
        name = safe_name(hl["title"])
        if highlight_filter and name != highlight_filter:
            continue
        out_dir = UNCATEGORIZED_HIGHLIGHTS_DIR / name

        media_r = requests.get(
            f"{IG_API_BASE}/{hl['id']}/media",
            params={"fields": "id,media_type,media_url,video_url,timestamp", "access_token": IG_TOKEN}
        ).json()
        items = media_r.get("data", [])

        if name not in manifest:
            manifest[name] = {"title": hl["title"], "items": []}

        for item in items:
            if item["id"] in existing_ids:
                skipped += 1
                continue
            media_url = item.get("video_url") or item.get("media_url")
            if not media_url:
                continue
            ext = "mp4" if item["media_type"] == "VIDEO" else "jpg"
            dest = out_dir / f"{item['id']}.{ext}"
            download_file(media_url, dest)

            label, source = audio_probe(dest) if ext == "mp4" else ("", "none")
            manifest[name]["items"].append({
                **item,
                "media_type": item["media_type"].lower(),
                "local_path": str(dest),
                "category": "uncategorized",
                "tags": [],
                "original_music": label,
                "music_source": source,
            })
            downloaded += 1

            with open(HIGHLIGHTS_MANIFEST, "w") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

    return {
        "highlights_count": len(highlights),
        "downloaded": downloaded,
        "skipped": skipped,
    }


if __name__ == "__main__":
    result = run()
    print(f"Done. {result['highlights_count']} highlights, {result['downloaded']} downloaded, {result['skipped']} skipped.")
