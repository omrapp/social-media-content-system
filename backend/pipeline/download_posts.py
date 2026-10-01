import json
import requests

from backend.config import IG_TOKEN, IG_USER_ID, IG_API_BASE, ORGANIZED_DIR, POSTS_MANIFEST
from backend.pipeline.audio_probe import probe as audio_probe

UNCATEGORIZED_DIR = ORGANIZED_DIR / "uncategorized" / "posts"


def fetch_media_page(url):
    r = requests.get(url).json()
    return r.get("data", []), r.get("paging", {}).get("next")


def download_file(url, dest):
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, stream=True)
    with open(dest, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)


def run():
    url = (
        f"{IG_API_BASE}/{IG_USER_ID}/media"
        f"?fields=id,media_type,media_url,video_url,timestamp,caption"
        f"&limit=50&access_token={IG_TOKEN}"
    )

    existing_ids = set()
    manifest = []
    if POSTS_MANIFEST.exists():
        manifest = json.loads(POSTS_MANIFEST.read_text())
        existing_ids = {item["id"] for item in manifest}

    downloaded = 0
    skipped = 0

    while url:
        items, url = fetch_media_page(url)
        for item in items:
            if item["id"] in existing_ids:
                skipped += 1
                continue
            media_url = item.get("video_url") or item.get("media_url")
            if not media_url:
                continue
            ext = "mp4" if item["media_type"] == "VIDEO" else "jpg"
            dest = UNCATEGORIZED_DIR / f"{item['id']}.{ext}"
            download_file(media_url, dest)

            label, source = audio_probe(dest) if ext == "mp4" else ("", "none")
            manifest.append({
                **item,
                "media_type": item["media_type"].lower(),
                "local_path": str(dest),
                "category": "uncategorized",
                "tags": [],
                "original_music": label,
                "music_source": source,
            })
            downloaded += 1

            with open(POSTS_MANIFEST, "w") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

    return {"downloaded": downloaded, "skipped": skipped, "total": len(manifest)}


if __name__ == "__main__":
    result = run()
    print(f"Done. {result['downloaded']} downloaded, {result['skipped']} skipped.")
