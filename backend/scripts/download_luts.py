"""
Download LUTs into the curation staging area (assets/cubes/).  ── MANUAL ──

USER-RUN helper (not called by the pipeline). It feeds assets/cubes/ so you can
then run `python -m backend.scripts.curate_luts --apply` to pick + tag the keepers.

────────────────────────────────────────────────────────────────────────────
fixthephoto.com — JS / popup gated + Google reCAPTCHA
────────────────────────────────────────────────────────────────────────────
On https://fixthephoto.com/ground-control-luts each LUT sits behind a "Download
Free LUTS" button: you select the file (the first radio option), click download,
an email popup appears — and CLOSING that popup starts the zip download. BUT the
button also fires Google **reCAPTCHA v2**. A real browser with a normal profile
passes it invisibly; an automated/headless one usually gets challenged and the
download stalls. So we drive a real browser (Playwright) **headful by default**
with a persistent profile, select the free option, click download, dismiss the
popup, and capture the file — pausing so YOU can solve a captcha if one pops up.

  ONE-TIME setup (Playwright + a browser binary):
      pip install playwright          # if not already installed
      python -m playwright install chromium

  Then (a window opens — leave it focused, solve a captcha if asked):
      python -m backend.scripts.download_luts fixthephoto
      python -m backend.scripts.download_luts fixthephoto --limit 5    # try a few
      python -m backend.scripts.download_luts fixthephoto --headless   # no window (often captcha-blocked)

  The persistent profile (under <dest>/.ftp_profile) builds reCAPTCHA reputation,
  so after the first run or two the captcha usually stops appearing.

There is also a reliable direct-URL mode for any LUT source that serves real file
links (most free-LUT sites do) — no browser needed:

      python -m backend.scripts.download_luts urls --file my_luts.txt

Both modes: --dest defaults to assets/cubes/, --limit caps count, --delay sets the
polite gap. .zip archives are auto-extracted (*.cube only); .rar is saved as-is
(no stdlib rar support — extract it yourself).
"""
import argparse
import io
import re
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from backend.config import CUBES_STAGING_DIR

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
BASE = "https://fixthephoto.com"

# Collection slugs on fixthephoto that host the Ground-Control-style free LUTs.
# Each exposes /<slug>/download-<N> landing pages. Extend as you find more.
COLLECTIONS = ["ground-control-luts", "vintage-lut", "lut-color-grading"]

FILE_LINK_RE = re.compile(
    r'https?://[^\s"\'<>]+?\.(?:zip|cube|rar|3dl)'
    r'|https?://drive\.google\.com/[^\s"\'<>]+'
    r'|https?://(?:www\.)?dropbox\.com/[^\s"\'<>]+'
    r'|https?://(?:www\.)?mediafire\.com/[^\s"\'<>]+',
    re.I,
)
DOWNLOAD_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']*?/download-\d+)["\']', re.I)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def _safe_name(url: str, fallback: str) -> str:
    name = Path(urlparse(url).path).name
    return name or fallback


def _save_bytes(content: bytes, name: str, dest: Path, label: str) -> int:
    """Save raw bytes; if it's a zip, extract *.cube only. Returns # .cube written."""
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    if zipfile.is_zipfile(io.BytesIO(content)):
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for member in zf.namelist():
                if member.lower().endswith(".cube") and not member.endswith("/"):
                    (dest / f"{label}_{Path(member).name}").write_bytes(zf.read(member))
                    written += 1
        print(f"    extracted {written} .cube from {name}")
    else:
        (dest / name).write_bytes(content)
        if name.lower().endswith(".cube"):
            written = 1
        print(f"    saved {name} ({len(content)} bytes)"
              + ("  [rar — extract manually]" if name.lower().endswith(".rar") else ""))
    return written


# ── direct-URL mode (reliable, requests only) ───────────────────────────────


def _download_file(sess: requests.Session, url: str, dest: Path, label: str) -> int:
    if "drive.google.com" in url:
        m = re.search(r"/d/([^/]+)", url) or re.search(r"[?&]id=([^&]+)", url)
        if m:
            url = f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    try:
        r = sess.get(url, timeout=60, allow_redirects=True)
        r.raise_for_status()
        return _save_bytes(r.content, _safe_name(url, f"{label}.bin"), dest, label)
    except Exception as exc:
        print(f"    ! download failed: {url} ({exc})")
        return 0


def run_urls(url_file: Path, dest: Path, limit: int | None, delay: float) -> None:
    if not url_file.exists():
        print(f"error: url file not found: {url_file}", file=sys.stderr)
        raise SystemExit(2)
    urls = [
        ln.strip() for ln in url_file.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if limit:
        urls = urls[:limit]
    sess = _session()
    print(f"Downloading {len(urls)} direct URL(s) → {dest}\n")
    total = 0
    for i, url in enumerate(urls, 1):
        label = f"url_{i:03d}_" + re.sub(r"[^a-z0-9]+", "_", Path(urlparse(url).path).stem.lower())[:40]
        print(f"[{i}/{len(urls)}] {url}")
        total += _download_file(sess, url, dest, label)
        time.sleep(delay)
    print(f"\nDone. {total} .cube file(s) written to {dest}")


# ── fixthephoto mode (Playwright browser automation) ────────────────────────


def _collect_landing_urls(sess: requests.Session) -> list[str]:
    urls: list[str] = []
    for slug in COLLECTIONS:
        page = f"{BASE}/{slug}"
        try:
            html = sess.get(page, timeout=30).text
        except Exception as exc:
            print(f"  ! could not load {page} ({exc})")
            continue
        found = {urljoin(page + "/", h) for h in DOWNLOAD_HREF_RE.findall(html)}
        if not found:
            found = {f"{BASE}/{slug}/download-{i}" for i in range(1, 11)}
        print(f"  {slug}: {len(found)} download pages")
        urls.extend(sorted(found, key=lambda u: int(re.search(r'download-(\d+)', u).group(1))))
    return urls


# The free-download trigger (loads reCAPTCHA + the email popup), with fallbacks.
_DL_TRIGGER_SELECTORS = [
    "a.btn-newpl-one",
    "a.generate-recaptcha",
    "a:has-text('Download Free')",
    "form.buypresetform button.submit-button",
]
_POPUP_CLOSE_SELECTORS = [
    ".free-preset-popup .close",
    "a.fancybox-close",
    ".fancybox-close-small",
    ".fancybox-item.fancybox-close",
    "[title='Close']",
]


def _grab_one(page, url: str, dest: Path, timeout_ms: int) -> int:
    """Drive a single download-N page: pick the free option, click download,
    dismiss the email popup (solving a captcha if it appears), capture the file.
    Returns # .cube written."""
    label = "ftp_" + re.sub(r"[^a-z0-9]+", "_", urlparse(url).path.strip("/").lower())
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

    # The buy/download form is hydrated by JS — wait for it before locating.
    try:
        page.wait_for_selector("form.buypresetform", timeout=20000)
    except Exception:
        print("    ! download form never appeared — skipping")
        return 0
    page.wait_for_timeout(1500)

    # Select the free option — the first radio, marked data-newpl="1".
    try:
        radio = page.locator("input[name='tool'][data-newpl='1']").first
        if radio.count() == 0:
            radio = page.locator("input[name='tool']").first
        radio.check(timeout=4000)
    except Exception:
        pass  # some pages auto-select; proceed anyway

    try:
        with page.expect_download(timeout=timeout_ms) as dl_info:
            clicked = False
            for sel in _DL_TRIGGER_SELECTORS:
                try:
                    btn = page.locator(sel).first
                    if btn.count():
                        btn.click(timeout=3000, no_wait_after=True)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                print("    ! no download trigger matched — skipping")
                return 0
            # A reCAPTCHA may load now; closing the email popup fires the
            # download. Poll for the popup-close while the captcha is (in
            # headful) solved by the user; expect_download keeps waiting.
            deadline = time.time() + timeout_ms / 1000 - 2
            while time.time() < deadline:
                closed = False
                for sel in _POPUP_CLOSE_SELECTORS:
                    try:
                        c = page.locator(sel).first
                        if c.count() and c.is_visible():
                            c.click(timeout=1500, no_wait_after=True)
                            closed = True
                            break
                    except Exception:
                        continue
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                if closed:
                    break
                page.wait_for_timeout(1500)
        download = dl_info.value
    except Exception as exc:
        print(f"    ! no download captured ({str(exc)[:120]}) — likely reCAPTCHA; "
              "run headful and solve it, or use `urls` mode")
        return 0

    try:
        content = Path(download.path()).read_bytes()
        name = download.suggested_filename or _safe_name(url, f"{label}.zip")
        return _save_bytes(content, name, dest, label)
    except Exception as exc:
        print(f"    ! save failed ({exc})")
        return 0


def run_fixthephoto(dest: Path, limit: int | None, delay: float, headless: bool) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("error: Playwright not installed. Run:\n"
              "  pip install playwright && python -m playwright install chromium",
              file=sys.stderr)
        raise SystemExit(2)

    dest.mkdir(parents=True, exist_ok=True)
    profile_dir = dest / ".ftp_profile"   # persistent → builds reCAPTCHA reputation

    sess = _session()
    print(f"Crawling fixthephoto collections {COLLECTIONS} …")
    landing = _collect_landing_urls(sess)
    if limit:
        landing = landing[:limit]
    print(f"\n{len(landing)} download pages to fetch via browser "
          f"({'headless' if headless else 'headful — solve any captcha in the window'})\n")

    total = 0
    failed: list[str] = []
    with sync_playwright() as p:
        try:
            # Persistent context keeps cookies/captcha reputation between runs.
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir), headless=headless,
                accept_downloads=True, user_agent=UA,
            )
        except Exception as exc:
            print(f"error: could not launch chromium ({str(exc)[:160]})\n"
                  "Run: python -m playwright install chromium", file=sys.stderr)
            raise SystemExit(2)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for i, url in enumerate(landing, 1):
            print(f"[{i}/{len(landing)}] {url}")
            n = _grab_one(page, url, dest, timeout_ms=60000)
            total += n
            if n == 0:
                failed.append(url)
            page.wait_for_timeout(int(delay * 1000))
        ctx.close()

    if failed:
        report = dest / "_failed.txt"
        report.write_text(
            "# fixthephoto pages where no download was captured (selectors may have\n"
            "# changed, or the LUT is paid-only). Open these manually if needed.\n\n"
            + "\n".join(failed) + "\n"
        )
        print(f"\n{len(failed)} page(s) failed → listed in {report}")
    print(f"\nDone. {total} .cube file(s) written to {dest}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Download LUTs into assets/cubes/ for curation.")
    sub = ap.add_subparsers(dest="mode", required=True)

    ftp = sub.add_parser("fixthephoto", help="browser-drive the fixthephoto free-LUT downloads")
    ftp.add_argument("--headless", action="store_true",
                     help="run without a window (often reCAPTCHA-blocked; default is headful)")

    u = sub.add_parser("urls", help="download a text file of direct LUT URLs (reliable)")
    u.add_argument("--file", type=Path, required=True, help="text file: one direct URL per line")

    for p in (ftp, u):
        p.add_argument("--dest", type=Path, default=CUBES_STAGING_DIR)
        p.add_argument("--limit", type=int, default=None, help="cap number of downloads")
        p.add_argument("--delay", type=float, default=1.5, help="seconds between requests (be polite)")

    args = ap.parse_args()
    if args.mode == "fixthephoto":
        run_fixthephoto(args.dest, args.limit, args.delay, args.headless)
    else:
        run_urls(args.file, args.dest, args.limit, args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
