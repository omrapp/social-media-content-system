"""
Tiered music scraper — populates assets/music/packs/<pillar>/ with royalty-free
travel tracks and writes enriched metadata to assets/music/cache.json.

Sources (in tier order per pillar, stops when --target reached):
  1. Jamendo API    — royalty-free instrumental tracks via existing music_fetcher
                      API; reuses JAMENDO_CLIENT_ID from .env. Requires key.
  2. Pixabay        — free, commercial-ok, no attribution. JS-rendered site.
                      Requires Playwright (see Setup below).
  3. Chosic         — vlog aggregator. CC0/Pixabay-licensed only; CC-BY skipped.

Cache format (backward-compatible superset of existing {id, filename, title}):
  {
    "nature": [
      {"id":"1460440","filename":"1460440.mp3","title":"...","source":"jamendo",
       "duration":142,"popularity":880,"license":"cc0","mood":"ambient cinematic"}
    ]
  }
  Old entries (missing the new fields) still work — selector treats them neutral.

Setup (one-time, required for Pixabay tier):
    pip install playwright && playwright install chromium

Usage:
    # Full run — all pillars, all sources, 30 tracks each
    python -m backend.scripts.scrape_music --pillar all --target 30

    # Single pillar, Jamendo only (no Playwright needed)
    python -m backend.scripts.scrape_music --pillar nature --source jamendo --target 30

    # Preview what would be downloaded without writing any files
    python -m backend.scripts.scrape_music --pillar all --dry-run

    # Fill only pillars that have fewer than target tracks
    python -m backend.scripts.scrape_music --pillar all --target 30 --skip-existing

    # Probe downloaded files to fill missing duration (slow; uses ffprobe)
    python -m backend.scripts.scrape_music --pillar all --probe

After running: upload assets/music/packs/ and assets/music/cache.json to server.
"""

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests

from backend.config import JAMENDO_CLIENT_ID, MUSIC_DIR
from backend.pipeline.music_fetcher import (
    JAMENDO_API, CATEGORY_TAGS, PACKS_DIR, CACHE_FILE,
    _load_cache, _save_cache,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PILLARS = list(CATEGORY_TAGS.keys())  # hidden_gem, budget, culture, nature, food, beach

# Pixabay search terms per pillar (travel-vlog/cinematic mood)
PILLAR_PIXABAY_QUERIES = {
    "hidden_gem": "travel cinematic",
    "budget":     "travel vlog acoustic",
    "culture":    "epic cinematic",
    "nature":     "nature ambient",
    "food":       "jazz lounge",
    "beach":      "tropical summer",
}

# Chosic category pages — vlog section covers most moods
CHOSIC_VLOG_URL = "https://www.chosic.com/free-music/vlog/"

# Polite delay between HTTP requests (seconds)
_POLITE_DELAY = 1.0

# Headers for requests (avoids 403 on some sites)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ffprobe_duration(path: Path) -> float | None:
    """Return audio duration via ffprobe, or None if unavailable."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            stderr=subprocess.DEVNULL, timeout=15,
        )
        return float(out.strip())
    except Exception:
        return None


def _parse_cc_license(url: str) -> str:
    """Reduce a CC URL to a short label: cc0, cc-by, cc-by-sa, pixabay, etc."""
    url = (url or "").lower()
    if "zero" in url or "cc0" in url:
        return "cc0"
    if "by-sa" in url:
        return "cc-by-sa"
    if "by-nc" in url:
        return "cc-by-nc"
    if "by" in url:
        return "cc-by"
    if "pixabay" in url:
        return "pixabay"
    return "unknown"


def _save_mp3(url: str, dest: Path, dry_run: bool) -> bool:
    """Download url → dest. Returns True on success. No-op in dry_run mode."""
    if dry_run:
        print(f"    [dry-run] would download → {dest.name}")
        return True
    if dest.exists():
        return True
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=60, stream=True)
        if resp.status_code != 200:
            print(f"    ✗ HTTP {resp.status_code} for {url}")
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"    ✗ download error: {e}")
        return False


def _existing_ids(cache: dict, pillar: str) -> set[str]:
    return {t["id"] for t in cache.get(pillar, [])}


def _count_on_disk(pillar: str) -> int:
    d = PACKS_DIR / pillar
    return len(list(d.glob("*.mp3"))) if d.is_dir() else 0


# ---------------------------------------------------------------------------
# Tier 1: Jamendo
# ---------------------------------------------------------------------------

def _jamendo_scrape(pillar: str, need: int, cache: dict,
                    dry_run: bool, probe: bool) -> list[dict]:
    """Fetch + download up to *need* Jamendo tracks for *pillar*.

    Reuses the existing JAMENDO_API endpoint with pagination.
    Returns list of new manifest entries added.
    """
    if not JAMENDO_CLIENT_ID:
        print("  [jamendo] JAMENDO_CLIENT_ID not set — skipping")
        return []

    mood = CATEGORY_TAGS.get(pillar, CATEGORY_TAGS["hidden_gem"])
    existing = _existing_ids(cache, pillar)
    added: list[dict] = []
    offset = 0
    per_page = 20

    while len(added) < need:
        try:
            resp = requests.get(JAMENDO_API, params={
                "client_id": JAMENDO_CLIENT_ID,
                "format": "json",
                "limit": per_page,
                "offset": offset,
                "fuzzytags": mood,
                "vocalinstrumental": "instrumental",
                "audiodownload_allowed": "true",
                "include": "musicinfo licenses",
                "order": "popularity_total",
            }, headers=_HEADERS, timeout=20)
        except Exception as e:
            print(f"  [jamendo] request error: {e}")
            break

        results = resp.json().get("results", []) if resp.status_code == 200 else []
        if not results:
            break

        for track in results:
            if len(added) >= need:
                break
            tid = str(track.get("id", ""))
            if tid in existing:
                continue

            audio_url = track.get("audiodownload") or track.get("audio")
            if not audio_url:
                continue

            dest = PACKS_DIR / pillar / f"{tid}.mp3"
            print(f"  [jamendo] {track.get('name', tid)[:60]}")
            if not _save_mp3(audio_url, dest, dry_run):
                continue

            duration = track.get("duration")
            if probe and not dry_run and not duration:
                duration = _ffprobe_duration(dest)

            # Parse license from the musicinfo block
            license_url = (track.get("license_ccurl") or
                           track.get("musicinfo", {}).get("license", ""))
            license_tag = _parse_cc_license(license_url)

            entry = {
                "id": tid,
                "filename": f"{tid}.mp3",
                "title": track.get("name", ""),
                "source": "jamendo",
                "duration": duration,
                "popularity": track.get("popularity_total") or track.get("stats", {}).get("rate", 0),
                "license": license_tag,
                "mood": mood,
            }
            existing.add(tid)
            added.append(entry)

        offset += per_page
        time.sleep(_POLITE_DELAY)

    return added


# ---------------------------------------------------------------------------
# Tier 2: Pixabay (Playwright — click-and-intercept)
# ---------------------------------------------------------------------------

def _pixabay_scrape(pillar: str, need: int, cache: dict,
                    dry_run: bool, probe: bool) -> list[dict]:
    """Click each Pixabay play button and intercept the CDN mp3 network request.

    Confirmed working: play button class .playOverlay--rDjnr triggers a
    cdn.pixabay.com/audio/...mp3 response. Title read from parent container DIV.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [pixabay] playwright not installed — run: pip install playwright && playwright install chromium")
        return []

    query = PILLAR_PIXABAY_QUERIES.get(pillar, "travel cinematic")
    url = f"https://pixabay.com/music/search/{requests.utils.quote(query)}/?order=ec"
    existing = {t["id"] for t in cache.get(pillar, []) if t.get("source") == "pixabay"}
    added: list[dict] = []

    print(f"  [pixabay] launching browser → {url}")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_HEADERS["User-Agent"])

            captured_mp3s: list[str] = []
            page.on("response", lambda r: captured_mp3s.append(r.url)
                    if ".mp3" in r.url and "cdn.pixabay.com" in r.url else None)

            page.goto(url, wait_until="networkidle", timeout=30_000)

            # Scroll to load more cards (20 cards/page; scroll for extra)
            scroll_rounds = max(2, need // 10 + 1)
            for _ in range(scroll_rounds):
                page.evaluate("window.scrollBy(0, 3000)")
                page.wait_for_timeout(1200)

            play_btns = page.query_selector_all(".playOverlay--rDjnr")
            print(f"  [pixabay] found {len(play_btns)} play buttons")

            for btn in play_btns:
                if len(added) >= need:
                    break

                before = len(captured_mp3s)
                try:
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    page.wait_for_timeout(1800)
                except Exception:
                    continue

                new_mp3s = captured_mp3s[before:]
                if not new_mp3s:
                    continue
                mp3_url = new_mp3s[0]

                # Stable ID from CDN filename (audio_<hash>.mp3)
                tid = Path(mp3_url.split("?")[0]).stem
                full_id = f"pxb_{tid}"
                if full_id in existing:
                    continue

                # Title from parent container
                title = btn.evaluate("""el => {
                    let node = el.parentElement;
                    for (let i = 0; i < 10 && node; i++) {
                        const t = node.querySelector('[class*="Title"],[class*="title"],h3,h2');
                        if (t && t.textContent.trim().length > 2)
                            return t.textContent.trim().slice(0, 80);
                        node = node.parentElement;
                    }
                    return '';
                }""") or tid

                dest = PACKS_DIR / pillar / f"{full_id}.mp3"
                print(f"  [pixabay] {title[:60]}")
                if not _save_mp3(mp3_url, dest, dry_run):
                    continue

                duration = None
                if probe and not dry_run:
                    duration = _ffprobe_duration(dest)

                entry = {
                    "id": full_id,
                    "filename": dest.name,
                    "title": title,
                    "source": "pixabay",
                    "duration": duration,
                    "popularity": None,
                    "license": "pixabay",
                    "mood": CATEGORY_TAGS.get(pillar, ""),
                }
                existing.add(full_id)
                added.append(entry)
                time.sleep(_POLITE_DELAY)

            browser.close()
    except Exception as e:
        print(f"  [pixabay] browser error: {e}")

    return added


# ---------------------------------------------------------------------------
# Tier 3: Chosic (Playwright — click-and-intercept)
# ---------------------------------------------------------------------------

def _chosic_scrape(pillar: str, need: int, cache: dict,
                   dry_run: bool, probe: bool) -> list[dict]:
    """Click each Chosic .wave-player and intercept the WP-uploads mp3 request.

    Confirmed working: .wave-player div triggers chosic.com/wp-content/uploads/...mp3.
    Title from .trackF-title-inside (first line = track name, second = artist).
    Note: Chosic mixes licenses; all tracks marked 'chosic' in manifest.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [chosic] playwright not installed — run: pip install playwright && playwright install chromium")
        return []

    existing = {t["id"] for t in cache.get(pillar, []) if t.get("source") == "chosic"}
    added: list[dict] = []

    print(f"  [chosic] launching browser → {CHOSIC_VLOG_URL}")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_HEADERS["User-Agent"])

            captured_mp3s: list[str] = []
            page.on("response", lambda r: captured_mp3s.append(r.url)
                    if ".mp3" in r.url and "chosic.com" in r.url else None)

            page.goto(CHOSIC_VLOG_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)  # let WaveSurfer finish wiring players

            wave_players = page.query_selector_all(".wave-player")
            print(f"  [chosic] found {len(wave_players)} tracks")

            for player in wave_players:
                if len(added) >= need:
                    break

                before = len(captured_mp3s)
                try:
                    player.scroll_into_view_if_needed()
                    player.click()
                    page.wait_for_timeout(2000)
                except Exception:
                    continue

                new_mp3s = captured_mp3s[before:]
                if not new_mp3s:
                    continue
                mp3_url = new_mp3s[0]

                tid = Path(mp3_url.split("?")[0]).stem
                full_id = f"chosic_{tid}"
                if full_id in existing:
                    continue

                # Title = first non-empty line of .trackF-title-inside text
                title = player.evaluate("""el => {
                    let node = el.parentElement;
                    for (let i = 0; i < 8 && node; i++) {
                        const t = node.querySelector('.trackF-title-inside,[class*=title]');
                        if (t) {
                            const lines = t.textContent.split('\\n').map(s=>s.trim()).filter(Boolean);
                            return lines[0] || '';
                        }
                        node = node.parentElement;
                    }
                    return '';
                }""") or tid

                dest = PACKS_DIR / pillar / f"{full_id}.mp3"
                print(f"  [chosic] {title[:60]}")
                if not _save_mp3(mp3_url, dest, dry_run):
                    continue

                duration = None
                if probe and not dry_run:
                    duration = _ffprobe_duration(dest)

                entry = {
                    "id": full_id,
                    "filename": dest.name,
                    "title": title,
                    "source": "chosic",
                    "duration": duration,
                    "popularity": None,
                    "license": "chosic",
                    "mood": CATEGORY_TAGS.get(pillar, ""),
                }
                existing.add(full_id)
                added.append(entry)
                time.sleep(_POLITE_DELAY)

            browser.close()
    except Exception as e:
        print(f"  [chosic] browser error: {e}")

    return added


# ---------------------------------------------------------------------------
# Per-pillar orchestration
# ---------------------------------------------------------------------------

def _scrape_pillar(pillar: str, target: int, sources: list[str],
                   cache: dict, skip_existing: bool,
                   dry_run: bool, probe: bool) -> int:
    """Download up to *target* tracks from each source independently for *pillar*.

    Each source runs its own quota — Jamendo gets *target* tracks, Pixabay gets
    *target* tracks, Chosic gets *target* tracks. Sources do NOT stop each other.
    """
    pillar_cache = cache.setdefault(pillar, [])
    total_added = 0

    tier_fns = {
        "jamendo": _jamendo_scrape,
        "pixabay": _pixabay_scrape,
        "chosic":  _chosic_scrape,
    }

    for src in sources:
        fn = tier_fns.get(src)
        if not fn:
            print(f"  unknown source: {src}")
            continue

        # Count tracks from THIS source already present on disk
        src_on_disk = sum(
            1 for t in pillar_cache
            if t.get("source") == src
            and (PACKS_DIR / pillar / t.get("filename", "")).exists()
        )

        print(f"\n── {pillar.upper()} / {src} ── {src_on_disk}/{target} on disk")

        if skip_existing and src_on_disk >= target:
            print(f"  already at {target}, skipping")
            continue

        need = target - src_on_disk
        print(f"  fetching {need} more from {src}")

        try:
            new_entries = fn(pillar, need, cache, dry_run, probe)
        except Exception as e:
            print(f"  [ERROR] {src} failed: {e}")
            new_entries = []

        for entry in new_entries:
            pillar_cache.append(entry)
            total_added += 1

        if not dry_run and new_entries:
            _save_cache(cache)

    return total_added


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _probe_existing(cache: dict, dry_run: bool):
    """Back-fill duration for any cached entry whose file exists but duration is None."""
    changed = False
    for pillar, entries in cache.items():
        for entry in entries:
            if entry.get("duration"):
                continue
            path = PACKS_DIR / pillar / entry.get("filename", "")
            if not path.exists():
                continue
            dur = _ffprobe_duration(path)
            if dur:
                entry["duration"] = dur
                print(f"  probed {entry['filename']}: {dur:.1f}s")
                changed = True
    if changed and not dry_run:
        _save_cache(cache)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape royalty-free travel music into assets/music/packs/"
    )
    parser.add_argument(
        "--pillar", default="all",
        help=f"Pillar name or 'all'. Choices: all, {', '.join(PILLARS)}",
    )
    parser.add_argument(
        "--target", type=int, default=30,
        help="Tracks per pillar to aim for (default: 30)",
    )
    parser.add_argument(
        "--source", default="jamendo,pixabay,chosic",
        help="Comma-separated sources in priority order (default: jamendo,pixabay,chosic)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List tracks that would be downloaded without writing any files",
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip pillars that already have --target tracks on disk",
    )
    parser.add_argument(
        "--probe", action="store_true",
        help="Use ffprobe to fill missing duration in downloaded files (slower)",
    )
    args = parser.parse_args()

    sources = [s.strip().lower() for s in args.source.split(",") if s.strip()]
    pillars = PILLARS if args.pillar == "all" else [args.pillar]

    invalid = [p for p in pillars if p not in PILLARS]
    if invalid:
        parser.error(f"Unknown pillar(s): {invalid}. Valid: {PILLARS}")

    cache = _load_cache()

    if args.probe and args.pillar == "all":
        print("\n── PROBE EXISTING ──")
        _probe_existing(cache, args.dry_run)

    total = 0
    for pillar in pillars:
        added = _scrape_pillar(
            pillar=pillar,
            target=args.target,
            sources=sources,
            cache=cache,
            skip_existing=args.skip_existing,
            dry_run=args.dry_run,
            probe=args.probe,
        )
        total += added

    print(f"\n{'[dry-run] ' if args.dry_run else ''}Done — {total} tracks added total.")
    print(f"Cache: {CACHE_FILE}")
    print(f"Packs: {PACKS_DIR}")
    if not args.dry_run:
        print("Upload assets/music/packs/ + assets/music/cache.json to server when ready.")


if __name__ == "__main__":
    main()
