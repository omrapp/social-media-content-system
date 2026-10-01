import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
# Downloaded IG content lives outside the repo in prod (e.g. /srv/social-media-cms/data).
# Override with DATA_DIR; defaults to repo-local downloads/ for dev.
DOWNLOADS_DIR = Path(os.environ.get("DATA_DIR", ROOT_DIR / "downloads"))
ORGANIZED_DIR = DOWNLOADS_DIR / "organized"
# User-uploaded clips (local file + URL fetch) land here, hidden from the
# IG By-Category funnel (downloads._organized_breakdown skips this dir).
UPLOADS_DIR = ORGANIZED_DIR / "uploads"
POSTS_DIR = DOWNLOADS_DIR / "posts"
HIGHLIGHTS_DIR = DOWNLOADS_DIR / "highlights"
REELS_READY_DIR = ROOT_DIR / "reels_ready"
THUMBS_DIR = REELS_READY_DIR / "thumbs"
# Multi-clip merge stage scratch + output (merge_clips.py). Per-clip normalized
# segments are written here before the xfade chain; the final merged reel lives
# here too until it flows through the normal edit/upload pipeline.
MERGE_DIR = REELS_READY_DIR / "merge"
# Reel Editor scratch (editor_proxy.py proxies, layer textfiles). A SIBLING of
# MERGE_DIR — never inside it: merge_clips._cleanup() does
# shutil.rmtree(MERGE_DIR/<merge_id>) after every render and would take the
# proxy cache with it. Served only through the signed /api/editor/proxy route,
# never a StaticFiles mount. Swept on a TTL by daemon.py (editor.proxy_ttl_days).
EDITOR_DIR = REELS_READY_DIR / "editor"
ASSETS_DIR = ROOT_DIR / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
LUTS_DIR = ASSETS_DIR / "luts"
# Curated cinematic LUTs (content-aware grade) live in a subdir so they coexist
# with the legacy warm/cool/vintage.cube fallbacks. catalog.json maps each one to
# mood/pillar tags. CUBES_STAGING_DIR is the raw vendor download area — read only
# by the manual curate_luts.py script, never at runtime.
LUTS_CINEMATIC_DIR = LUTS_DIR / "cinematic"
LUT_CATALOG_PATH = LUTS_DIR / "catalog.json"
CUBES_STAGING_DIR = ASSETS_DIR / "cubes"
FONTS_DIR = ASSETS_DIR / "fonts"
INTRO_DIR = ASSETS_DIR / "intros"
OUTRO_DIR = ASSETS_DIR / "outros"
# Editor image/sticker overlays (v2.0.0 Phase 5). Ships EMPTY — the library is
# whatever the user uploads via /api/assets/stickers/upload. Sits under
# ASSETS_DIR because that is the containment root editor_edl._safe_sticker()
# checks an EDL ImageLayer.asset against.
STICKERS_DIR = ASSETS_DIR / "stickers"
# Supabase Storage bucket backing the `assets` table (music/font/lut/intro/outro
# public URLs). Public-read bucket — non-sensitive branding/music/LUT assets,
# not user data. Created manually in the Supabase dashboard (see migration
# 014_assets_table.sql header).
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "assets")
# Decaption (remove burned-in IG captions/watermarks). YOLO11s detect weights are
# fetched manually into DECAPTION_MODELS_DIR (see backend/scripts/setup_decaption.py);
# per-clip cleaned outputs are cached under DECAPTIONED_DIR and reused via
# media.decaptioned_path. BOTH live under DATA_DIR (the bind-mounted /srv/social-media-cms/
# data volume in prod) — NOT under assets/, which is baked into the Docker image — so
# a one-time weight fetch and the clean-cache both survive redeploys. Auto-created below.
DECAPTION_MODELS_DIR = DOWNLOADS_DIR / "models"
DECAPTIONED_DIR = DOWNLOADS_DIR / "decaptioned"
# Voiceover (edge-tts narration + burned subtitles). Generated audio/SRT are
# cheap to regenerate but cached on media.voiceover_path like decaption; lives
# under DATA_DIR so it survives redeploys same as DECAPTIONED_DIR.
VOICEOVER_DIR = DOWNLOADS_DIR / "voiceover"
LOGS_DIR = ROOT_DIR / "logs"

# --- Audio auto-music heuristics (video_edit) ---
# Clip gets background music (replacing original) when it has no audio stream,
# is near-silent, or is speech/noise-dominant (talking, loud voices, raw mic).
# Real music / pleasant ambient is left untouched.
AUDIO_SILENT_DB = float(os.environ.get("AUDIO_SILENT_DB", "-50"))      # mean_volume below this = silent
AUDIO_NOISY_DB = float(os.environ.get("AUDIO_NOISY_DB", "-30"))        # at/above this + speech-like = noisy
AUDIO_SPEECH_FLATNESS = float(os.environ.get("AUDIO_SPEECH_FLATNESS", "0.08"))  # flatness above this = non-tonal (speech/noise); music bulk sits <0.055

POSTS_MANIFEST = DOWNLOADS_DIR / "posts_manifest.json"
STORIES_MANIFEST = DOWNLOADS_DIR / "stories_manifest.json"
HIGHLIGHTS_MANIFEST = DOWNLOADS_DIR / "highlights_manifest.json"
QUEUE_FILE = ROOT_DIR / "queue.json"
SQLITE_DB = ROOT_DIR / "db" / "content.db"

IG_TOKEN = os.environ.get("IG_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
IG_API_BASE = f"https://graph.facebook.com/v20.0"
IG_USER_URL = f"{IG_API_BASE}/{IG_USER_ID}"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "google/gemma-4-31b-it:free"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
# Backend-only. Bypasses RLS for server-side writes (settings, media, posts, pipeline_runs).
# Never expose to frontend — Vercel bundles VITE_* envs into the client.
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

R2_ENDPOINT = os.environ.get("R2_ENDPOINT", "")
R2_ACCESS_KEY = os.environ.get("R2_ACCESS_KEY", "")
R2_SECRET_KEY = os.environ.get("R2_SECRET_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "travel-reels")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")
R2_MAX_GB = float(os.environ.get("R2_MAX_GB", "10"))
LOCAL_REELS_MAX_GB = float(os.environ.get("LOCAL_REELS_MAX_GB", "5"))
LOCAL_REELS_MIN_AGE_DAYS = int(os.environ.get("LOCAL_REELS_MIN_AGE_DAYS", "7"))

PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
JAMENDO_CLIENT_ID = os.environ.get("JAMENDO_CLIENT_ID", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
# Signing key for the ONE unauthenticated editor route (/api/editor/proxy/<hash>.mp4
# — a <video> element cannot send an Authorization header). Dedicated so a leaked
# proxy URL can never be replayed as a session token; falls back to the JWT secret
# so the feature works without extra ops setup.
EDITOR_MEDIA_SECRET = os.environ.get("EDITOR_MEDIA_SECRET", "") or SUPABASE_JWT_SECRET

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_MODE = os.environ.get("TELEGRAM_MODE", "poll")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

# Google Drive + Photos import (Download page → Google source). Single-account
# OAuth, mirrors the YouTube pattern: one refresh token for the account owner.
# Run backend/scripts/auth_google.py to mint GOOGLE_REFRESH_TOKEN (Drive readonly
# + Photos Picker scopes).
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")

TIKTOK_CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
TIKTOK_CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
TIKTOK_ACCESS_TOKEN = os.environ.get("TIKTOK_ACCESS_TOKEN", "")
TIKTOK_REFRESH_TOKEN = os.environ.get("TIKTOK_REFRESH_TOKEN", "")

# Decaption inference device. "cpu" (the VPS default) | "cuda" (future GPU worker).
DECAPTION_DEVICE = os.environ.get("DECAPTION_DEVICE", "cpu")

ZERNIO_API_KEY = os.environ.get("ZERNIO_API_KEY", "")
ZERNIO_IG_ACCOUNT_ID = os.environ.get("ZERNIO_IG_ACCOUNT_ID", "")
ZERNIO_TT_ACCOUNT_ID = os.environ.get("ZERNIO_TT_ACCOUNT_ID", "")

for d in [DOWNLOADS_DIR, ORGANIZED_DIR, UPLOADS_DIR, POSTS_DIR, HIGHLIGHTS_DIR, REELS_READY_DIR, THUMBS_DIR, MERGE_DIR, EDITOR_DIR, MUSIC_DIR, LUTS_DIR, LUTS_CINEMATIC_DIR, INTRO_DIR, OUTRO_DIR, STICKERS_DIR, DECAPTION_MODELS_DIR, DECAPTIONED_DIR, VOICEOVER_DIR, LOGS_DIR, SQLITE_DB.parent]:
    d.mkdir(parents=True, exist_ok=True)
