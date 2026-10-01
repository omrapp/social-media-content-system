import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.db import get_all_settings, get_setting, set_setting
from backend.api.auth import verify_token

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(verify_token)])

# Canonical default values. Seeded on startup; never overwrite if already present.
DEFAULTS: dict[str, dict] = {
    "approval": {
        "instagram_auto_enabled": False,
        "instagram_auto_minutes": 60,
        "tiktok_auto_enabled": False,
        "tiktok_auto_minutes": 60,
        "youtube_auto_enabled": True,
        "youtube_auto_minutes": 60,
        "require_manual_for_categories": [],
    },
    "schedule": {
        "daily_slots": ["08:00", "11:00", "14:00", "18:00", "21:00"],
        "timezone": "Asia/Jerusalem",
        "max_per_day": 5,
        "optimize_times": True,   # order free slots by historical engagement (Enh C)
    },
    "ai": {
        "classifier_model": "groq/openai/gpt-oss-120b",
        "caption_model": "groq/openai/gpt-oss-120b",  # primary; OpenRouter google/gemma-4-31b-it:free is fallback
        "refine_model": "google/gemma-4-31b-it:free",
    },
    "telegram": {
        "mode": "poll",
        "chat_id": "",
        "preview_push_enabled": True,
        "always_preview": True,       # push rich preview at creation even in auto-publish mode
        "rich_publish_notify": True,  # post-publish daemon notification loads media + full details
        "admin_controls": True,       # show extended admin buttons (edit/details/reschedule menu) on preview
    },
    "music": {
        "preferred_source": "licensed",
        "pixabay_query": "travel cinematic",
        "swap_on_detect_original": False,
        "mood_match": True,   # pick background music by caption-derived mood (Enh G)
        "favourite_boost": 3.0,     # score bonus when a track is admin-flagged favourite (1.9.0)
        "usage_weight": 0.3,        # usage_weight * log1p(usage_count) proven-track lift (1.9.0)
        "cooldown_recent_cap": 10,  # recently-picked cooldown window size; was hardcoded RECENT_CAP (1.9.0)
    },
    # Caption generation enhancements (Enh A/B/J/L)
    "caption": {
        "use_feedback": True,    # inject top-performing hooks into the generator (Enh A)
        "use_trends": True,      # inject weekly Google-Trends travel topics (Enh B)
        "self_critique": True,   # extra Haiku hooks-only refine pass (Enh J)
        "draft_with_groq": False,  # Track 3 (Enh L): draft on free Groq, polish on Haiku (cost→~$0)
        "use_hook_library": True,  # inject viral hook templates into caption prompt
        "hook_templates": [],      # user-supplied hook strings; empty = use code defaults
        "cta_style": "send",       # send | save | follow — last-line CTA style (default: sends-per-reach)
    },
    # Hashtag A/B testing (Enh D) + shadow-ban denylist (Enh L) + curated viral blending
    "hashtags": {
        "ab_test": True,   # coin-flip hashtags_en vs hashtags_en_b per post
        # Over-saturated / shadow-ban-prone tags stripped from generated sets.
        # Empty list → fall back to the built-in default denylist.
        "blocked": [],
        "curated_enabled": True,  # blend curated viral pool tags into every post
        "blend_count": 3,         # curated tags per post; 3 reach + 2 LLM niche fits 5-tag cap
        "pools": {
            "instagram": [],   # empty = use code defaults
            "tiktok": [],
            "youtube": [],
        },
    },
    # Monetization CTA injection — appended to caption body before hashtags.
    "monetize": {
        "enabled": False,
        "cta_text": "",
        "youtube_link": "",
        "platforms": ["instagram", "tiktok", "youtube"],
    },
    # Vision hook-scoring stage (Enh E)
    "vision": {
        "enabled": True,        # run classify_vision hook-scoring stage
        "provider": "auto",     # nightly backfill provider: "auto" | "groq" | "local"
        "nightly_limit": 50,    # max un-scored clips per nightly 03:00 backfill run
    },
    # Clip-selection what-works signal (Enh I) + quality gate (0.6.0)
    "selection": {
        "use_performance": True,    # blend realized category engagement into clip pick
        "performance_weight": 0.5,  # how hard proven categories lift hook_score in selection
        # — quality gate on existing fields (null-safe: missing data never rejects) —
        "min_duration_s": 10.0,     # reject clips shorter than this (seconds)
        "min_short_side": 720,      # reject below this resolution (short edge in px); 0 = off
        "min_hook_score": 0.0,      # reject below this predicted hook score; 0 = off (cold-start safe)
        "require_video_only": True, # only ever pick VIDEO media (images/carousels can't be Reels)
        # — blur/shake probe stage (0.6.0) —
        "quality_probe_enabled": True,  # run the FFmpeg blur/shake stage at creation
        "min_quality_score": 0.0,       # reject below this probe score (0-1); 0 = measure-only
        # — classification completeness gate —
        "require_classified": True,     # only pick clips with category + hook_score set; falls back if pool would be empty
        "category_cooldown_categories": 20,  # skip a category until this many OTHER distinct categories posted since; 0 = off (diverse strategy + merge auto-pick)
    },
    "taxonomy": {
        "categories": ["hidden_gem", "budget", "culture", "nature", "food", "beach"],
    },
    # User-uploaded clips (Download page → Upload). Local file + public URL fetch.
    "uploads": {
        "max_mb": 500,                                        # per-file size cap (local + URL fetch)
        "allowed_types": [".mp4", ".mov", ".m4v", ".webm"],   # extension allowlist
        "auto_probe": True,                                   # ffprobe duration/dims right after upload
        "url_fetch": True,                                    # allow server-side URL paste fetch (SSRF surface)
    },
    "platforms": {
        "instagram_enabled": True,
        "youtube_enabled": True,
        "tiktok_enabled": True,
        "instagram": {
            "hashtag_suffix": ["travelreels", "hiddengems", "exploremore"],
        },
        "tiktok": {
            "hashtag_suffix": ["fyp", "travel", "wanderlust"],
        },
        "youtube": {
            "hashtag_suffix": ["Shorts", "TravelShorts", "Travel"],
            "playlists_enabled": True,  # group videos by category into YT playlists
        },
    },
    # category → YouTube playlist_id cache (auto-populated on first publish per category)
    "youtube_playlists": {},
    "analytics": {
        "ingest_interval_hours": 6,
    },
    "video": {
        "auto_stabilize": True,
        "remove_watermarks": False,   # watermark blur off by default
        "watermark_position": "bottom",
        # Track 1 video-quality chain (Enh K) — free CPU-only FFmpeg filters.
        "enhance_quality": True,        # master toggle for the quality filter chain
        "denoise": True,                # hqdn3d light denoise (run before motion)
        "denoise_strength": "light",    # light | medium | strong
        "sharpen": True,                # contrast-adaptive sharpen (cas) after LUT
        "sharpen_amount": 0.4,          # cas strength 0.0–1.0
        "crf": 20,                      # x264 quality (lower = sharper, bigger file)
        "preset": "medium",             # x264 preset (medium balances the 2.5-cpu cap)
        "smooth_motion": False,         # minterpolate frame-interp (CPU-heavy, opt-in)
        "smooth_fps": 60,               # target fps when smooth_motion is on
    },
    # Decaption (v1.5.0) — remove burned-in IG captions/watermarks from raw clips.
    # Default-OFF, opt-in like merge/intro/cast. Each clip is cleaned ONCE (YOLO11
    # detect + OpenCV inpaint on ONNX Runtime) and cached on media.decaptioned_path,
    # then reused forever — the CPU cost is paid once per clip. Degrades to a
    # pass-through (clip kept, decaptioned=0) when the vendored model/weights are
    # absent. Requires manual setup: backend/scripts/setup_decaption.py.
    "decaption": {
        "enabled": False,          # master gate, opt-in
        "algorithm": "hybrid",     # hybrid | telea | ns (OpenCV inpaint method)
        "detect_mode": "auto",     # auto (YOLO11) | bottom | top | custom
        "custom_bbox": "",         # "x,y,w,h" when detect_mode=custom
        "min_confidence": 0.35,    # YOLO11 detection threshold
        "dilate_px": 6,            # expand mask around detected text before inpaint
        "fallback": "blur",        # blur | fill | none, on inpaint failure
    },
    # Content-aware colour grade (LUT) selection. Curated cinematic LUTs live in
    # assets/luts/cinematic/ (catalog.json maps mood/category tags). Falls back to
    # the legacy category→LUT map so it never grades worse than before.
    "color": {
        "lut_mode": "category",   # "category" | "mood" | "vision" | "fixed"
        "fixed_lut": "",        # LUTS_DIR-relative .cube when lut_mode=="fixed"
        "use_vision": False,    # allow AI-vision LUT override (adds a Groq call per edit)
        "intensity": 1.0,       # advisory 0.0–1.0 (full LUT applied; no blend in v1)
    },
    "pipeline": {
        "env_mode": "dev",
        "auto_publish_enabled": True,
        # Auto-create: daemon picks a raw clip at each daily slot and runs the full pipeline.
        # mode="approval" → Telegram preview pushed, waits for human approve.
        # mode="publish"  → post published automatically at the slot (no human gate).
        "auto_create_enabled": True,
        "auto_create_mode": "approval",
        "auto_create_strategy": "diverse",   # "best" | "random" | "diverse"
        "auto_create_category": "",          # optional category filter (empty = any)
        "auto_create_reel_type": "merge",   # "merge" (multi-clip montage) | "single" (one clip) — which pipeline the daemon runs at each slot
        "stages_enabled": {
            "index": True,
            "classify": True,
            "resize": True,
            "edit": True,
            "caption": True,
            "upload": True,
        },
    },
    # Local disk management for the reels_ready directory.
    "storage": {
        "reels_max_gb": 5,        # hard cap on local reels_ready dir size in GB
        "reels_min_age_days": 7,  # minimum file age (days) before eligible for auto-deletion
    },
    # Intro (Splash) screen — prepended to every reel when enabled.
    "intro": {
        "enabled": False,
        "mode": "generated",           # "generated" | "asset"
        "asset_file": "",              # filename in assets/intros/ when mode=asset
        "duration_s": 1.5,             # hold duration in seconds
        "animation": "fade",           # "none" | "fade" | "zoom"
        "bg_color": "#000000",
        "bg_opacity": 0.15,            # 0.0–1.0 background opacity; default semi-transparent
        "text_padding_h": 40,          # horizontal padding (px) applied to all text
        # Header element
        "header_enabled": True,
        "header_text": "",             # custom text; empty = ig_handle from branding
        "header_color": "#ffffff",
        "header_font": "",
        "header_font_size": 52,
        "header_order": 0,
        "header_bottom_padding": 0,
        # Sub-header element
        "subheader_enabled": True,
        "subheader_text": "",          # custom text; empty = skip
        "subheader_color": "#cccccc",
        "subheader_font": "",
        "subheader_font_size": 36,
        "subheader_order": 1,
        "subheader_bottom_padding": 16,
        # Tags element (comma-joined; hidden if empty)
        "show_tags": True,
        "tags_color": "#ffffff",
        "tags_font": "",
        "tags_font_size": 40,
        "tags_order": 2,
        "tags_bottom_padding": 0,
        # Category element
        "show_category": True,
        "category_color": "#aaaaaa",
        "category_font": "",
        "category_font_size": 30,
        "category_order": 3,
        "category_bottom_padding": 0,
        # Handle element
        "show_handle": True,
        "handle_color": "#ffffff",
        "handle_font": "",
        "handle_font_size": 28,
        "handle_order": 5,
        "handle_bottom_padding": 0,
        # Hook headline element (A2)
        "show_hook": False,
        "hook_source": "caption_line1",  # "caption_line1" | "manual"
        "hook_text": "",                  # used when hook_source="manual"
        "hook_color": "#ffffff",
        "hook_font": "",
        "hook_font_size": 56,
        "hook_order": -1,                 # renders before all other elements
        "hook_bottom_padding": 24,
    },
    # Cast (Outro) screen — appended to every reel when enabled.
    "cast": {
        "enabled": False,
        "mode": "generated",
        "asset_file": "",
        "duration_s": 1.5,
        "animation": "fade",
        "bg_color": "#000000",
        "bg_opacity": 0.15,
        "text_padding_h": 40,
        # CTA element
        "cta_enabled": True,
        "cta_text": "Send this to your travel buddy 🌍",
        "cta_color": "#ffffff",
        "cta_font": "",
        "cta_font_size": 52,
        "cta_order": 0,
        "cta_bottom_padding": 0,
        # Sub-header element
        "subheader_enabled": True,
        "subheader_text": "",
        "subheader_color": "#cccccc",
        "subheader_font": "",
        "subheader_font_size": 36,
        "subheader_order": 1,
        "subheader_bottom_padding": 16,
        # Tags element (comma-joined; hidden if empty)
        "show_tags": True,
        "tags_color": "#ffffff",
        "tags_font": "",
        "tags_font_size": 40,
        "tags_order": 2,
        "tags_bottom_padding": 0,
        # Episode element
        "show_episode": True,
        "episode_color": "#aaaaaa",
        "episode_font": "",
        "episode_font_size": 30,
        "episode_order": 4,
        "episode_bottom_padding": 0,
        # Handle element
        "show_handle": True,
        "handle_color": "#ffffff",
        "handle_font": "",
        "handle_font_size": 28,
        "handle_order": 5,
        "handle_bottom_padding": 0,
        # Minimal CTA mode (A6)
        "minimal_cta": False,             # when True + cta is a send-prompt, suppress all other cast elements
    },
    # Video branding overlay — configurable bottom (or top) bar baked onto every reel + thumbnail.
    "branding": {
        "overlay_enabled": False,   # master gate; opt-in (no surprise overlays on existing pipeline)
        "ig_handle": "",            # e.g. "@myhandle"; empty = no handle shown (overlay still draws)
        "custom_text": "",          # optional second line below location; empty = hidden
        "font": "",                 # font filename from assets/fonts/; empty = PlayfairDisplay fallback
        "font_size": 0,             # px — 0 = auto (proportional to bar_height)
        "bar_height": 45,           # px — full-width bar height
        "show_on_thumbnail": True,  # bake same bar onto the R2 thumbnail image
        "bar_bg_color": "#ffffff",  # bar background color (CSS hex, e.g. "#ffffff")
        "text_color": "#000000",    # text color (CSS hex, e.g. "#000000")
        "bar_opacity": 1.0,         # bar background opacity 0.0–1.0 (< 1 = semi-transparent)
        "bar_position": "bottom",   # "bottom" | "top"
        "location_side": "left",    # which side shows the tags text — "left" | "right"
        "handle_side": "right",     # which side shows @handle — "left" | "right"
    },
    # Cinematic category montage — stitch N clips into one 30–60s reel (merge_clips.py).
    "merge": {
        "enabled": False,            # master gate for the merge feature
        "auto_run": False,           # build a merged reel inside the normal create flow
        "clips_per_reel": 4,         # fallback clip count when auto_count is off (clamped 2–8)
        "target_duration_s": 30.0,   # target reel length in seconds (clamped 15–90)
        "selection_strategy": "diverse",  # auto-select pick: "best" | "diverse" | "random"
        "scene_aware": True,         # PySceneDetect best sub-shot per clip
        "transition": "fade",        # xfade transition (fade/dissolve/wipeleft/slideup/…)
        "transition_ms": 500,        # crossfade duration in ms (clamped 100–1500)
        "beat_sync": True,           # librosa beat-aligned cuts (lazy import)
        "min_clip_score": 0.0,       # reuse quality_score gate; 0 = off
        "cut_min_s": 1.5,            # min per-clip segment length (s) — rapid montage cuts
        "cut_max_s": 3.0,            # max per-clip segment length (s)
        "min_segments": 20,          # floor for auto-count: at least this many cuts/scenes (clamped 15–30)
        "min_main_videos": 10,       # best-effort: spread cuts across at least this many source videos
        "segments_per_clip": 3,      # distinct non-overlapping sub-shots pulled per source video (clamped 1–4)
        # Stock/local segment quota (1.8.1) — mix a floor of stock B-roll AND local
        # archive clips per montage; a thin pool on one side tops up from the other.
        "split_stock_local": True,   # enable the stock/local quota on auto-selected merges
        "min_stock_segments": 8,     # minimum stock (Pexels/Pixabay) clips per merged reel
        "min_local_segments": 12,    # minimum local-archive clips per merged reel
        # Auto-source stock (1.8.1) — when a category has NO stock yet, download a few
        # clips per provider on the fly. Needs stock.enabled + a provider key. Opt-in.
        "auto_fetch_stock": False,   # master gate for on-the-fly stock sourcing at merge time
        "auto_fetch_pexels": 3,      # clips to pull from Pexels when auto-sourcing
        "auto_fetch_pixabay": 3,     # clips to pull from Pixabay when auto-sourcing
        "cleanup_segments": True,    # delete the per-merge scratch dir after render (saves disk)
        "grade": "",                 # OpenMontage film-look grade profile ("" = off, keep LUT downstream)
        "grain": False,              # subtle film grain (noise) texture overlay
        "vignette": False,           # darken frame edges for a filmic look
        "auto_count": True,          # derive clip count from target_duration / avg cut
        "audio_mode": "music",       # "music" (licensed bed) | "original" (longest clip audio)
        "music_fade_s": 1.0,         # audio fade in/out seconds
        "slow_motion": True,         # slow-mo on alternating segments (duration-preserving)
        "slow_motion_factor": 0.85,  # PTS slow factor (<1 = slower); applied via setpts+trim
        "ken_burns": True,           # gentle zoompan push/pull per segment
        "transition_variety": True,  # rotate transitions across cuts instead of one fixed
        "loop_friendly": False,      # echo opener as last cut + skip music fade-out → seamless TikTok/IG loop (1.3.0)
        # --- Quality enhancement (1.7.0) — CPU-only, FFmpeg + cv2 (already deps) ---
        "adaptive_fx": True,         # per-clip content-adaptive FX: each clip's duration + slow-mo + Ken Burns + denoise/sharpen decided from its own cv2 metrics; off = fixed idx-parity rules (1.7.0)
        "smart_select": True,        # cv2 aesthetic scoring picks the best sub-shot per clip (sharpness/exposure/motion + variety) instead of longest (1.7.0)
        "select_sharpness_weight": 0.5,  # how hard sharpness weighs in the sub-shot score 0–1 (1.7.0)
        "select_min_sharpness": 0.0, # reject sub-shots below this normalized sharpness 0–1; 0 = off (1.7.0)
        "color_match": True,         # gentle per-segment gray-world white-balance nudge so mixed clips don't jump cut-to-cut (1.7.0)
        "deband": True,              # anti-banding pass after grade (cheap; kills sky/gradient banding) (1.7.0)
        "hard_cuts_on_beat": True,   # mix ~1-frame hard cuts among crossfades (every 3rd join) for punchier rhythm (1.7.0)
        "smooth_slowmo": False,      # minterpolate motion-compensated slow-mo (judder-free but CPU-HEAVY 2–5×); default off (1.7.0)
        "smooth_slowmo_max_s": 3.0,  # only interpolate slowed segments up to this length (s) to cap cost (1.7.0)
        "deblock": True,             # deblock IG-compression artifacts per segment (cheap) (1.7.0)
        "sharpen": False,            # per-segment contrast-adaptive sharpen; off by default to avoid double-sharpen with video.sharpen (1.7.0)
        "sharpen_amount": 0.3,       # cas strength 0–1 when merge.sharpen on (1.7.0)
        "strong_denoise": False,     # nlmeans strong denoise for grainy clips (CPU-HEAVY); default off (1.7.0)
        # --- Freshness & Variety (1.7.0) — anti-repeat + diversity, metadata-only memory ---
        "dedupe_enabled": True,          # anti-repeat: same-category reels avoid sub-shots used in recent reels (1.7.0)
        "subshot_cooldown_reels": 3,     # hard-exclude a used sub-shot for the last N same-category reels (clamped 0–20) (1.7.0)
        "dedupe_soft_weight": 0.5,       # score multiplier for reused sub-shots past the cooldown (clamped 0–1) (1.7.0)
        "proven_topup": True,            # top up a thin fresh pool with proven high-score segments (1.7.0)
        "proven_min_score": 0.5,         # only reuse previously-used segments scoring ≥ this (clamped 0–1) (1.7.0)
        "dynamic_count": True,           # scale count/cut-length to pool + target, maximize distinct clips (1.7.0)
        "max_cuts_per_source": 1,        # cuts per source clip before reusing one; 0 = auto ceil(n/sources) (clamped 0–8) (1.7.0)
    },
    # Stock B-roll sourcing (1.8.0) — search Pexels/Pixabay and index results as
    # raw media exactly like a manual upload, so merge_clips blends stock WITH
    # archive footage in the same category montage with zero merge-side changes.
    "stock": {
        "enabled": False,           # master gate, opt-in
        "source": "pexels",         # "pexels" | "pixabay" | "both"
        "per_category_query": {},   # optional {category: query} override; empty = built-in map
        "max_clips_per_search": 5,  # results fetched per search call
        "min_short_side": 720,      # reject clips below this short-edge px
        "min_duration_s": 5.0,      # reject clips shorter than this
    },
    # TTS voiceover + burned subtitles (1.8.0) — edge-tts narrates the caption
    # hook line; word-boundary timestamps from edge-tts itself (no whisper
    # needed since we already know the script) drive burned-in subtitles.
    # Default-OFF, opt-in like decaption/merge.
    "voiceover": {
        "enabled": False,              # master gate, opt-in
        "voice": "en-US-AriaNeural",   # edge-tts voice id
        "rate": "+0%",                 # edge-tts rate adjustment string
        "narration_source": "caption_hook",  # "caption_hook" | "manual"
        "subtitles_enabled": True,     # burn word-synced subtitles from edge-tts timestamps
        "subtitle_position": "bottom", # "bottom" | "top"
        "subtitle_font_size": 28,
        "subtitle_color": "#ffffff",
        "music_duck_volume": 0.08,     # music bed volume when voiceover present (below the ~0.15 default)
    },
    # Reel Editor (2.0.0) — CapCut-style timeline on the Preview page. Browser
    # previews from cached 480p proxies; export re-renders the reel with FFmpeg
    # from the saved EDL. Caps here are DoS/render-cost bounds, not UI polish.
    "editor": {
        "enabled": True,             # master gate for the /editor route + /api/editor/* (2.0.0)
        "proxy_height": 480,         # proxy short-edge px fed to the browser player (2.0.0)
        "proxy_ttl_days": 7,         # sweep cached proxies older than this (daemon job) (2.0.0)
        "autosave_seconds": 15,      # debounced autosave interval in the editor (2.0.0)
        "keep_versions": 20,         # EDL versions retained per reel; older ones pruned (2.0.0)
        "max_text_layers": 20,       # per-EDL cap on text overlays (DoS + render cost) (2.0.0)
        "max_image_layers": 10,      # per-EDL cap on image/sticker overlays (2.0.0)
        "max_cuts": 40,              # per-EDL cap on timeline cuts; matches merge_clips._MAX_CUTS (2.0.0)
        "export_mode": "overwrite",  # "overwrite" (update the same post) | "new_post" (2.0.0)
        "preview_lut": True,         # WebGL 3D-LUT preview in the browser; off = plain video (2.0.0)
    },
}

# Keys that must never be returned to the client — values are env-only secrets.
# UI surfaces only a boolean "is set" flag.
SECRET_ENV_KEYS = {
    "telegram.bot_token": "TELEGRAM_BOT_TOKEN",
    "ai.groq_api_key": "GROQ_API_KEY",
    "ai.openrouter_api_key": "OPENROUTER_API_KEY",
    "platforms.youtube_client_secret": "YOUTUBE_CLIENT_SECRET",
    "platforms.youtube_refresh_token": "YOUTUBE_REFRESH_TOKEN",
    "platforms.tiktok_client_secret": "TIKTOK_CLIENT_SECRET",
    "platforms.tiktok_access_token": "TIKTOK_ACCESS_TOKEN",
    "uploads.google_client_secret": "GOOGLE_CLIENT_SECRET",
    "uploads.google_refresh_token": "GOOGLE_REFRESH_TOKEN",
    "stock.pexels_api_key": "PEXELS_API_KEY",
    "stock.pixabay_api_key": "PIXABAY_API_KEY",
}


def seed_defaults():
    """Insert defaults for any group key that doesn't already exist."""
    existing = get_all_settings()
    for group, value in DEFAULTS.items():
        if group not in existing:
            set_setting(group, value)


class SettingsUpdate(BaseModel):
    group: str
    value: dict


def _merge_with_defaults(stored: dict) -> dict:
    """Per-group deep merge so newly-added default keys surface even when a
    group was seeded earlier with fewer keys (a shallow {**DEFAULTS, **stored}
    would let a stale stored group hide new keys from the UI). Stored values
    still win on conflict."""
    merged: dict = {}
    for group, default in DEFAULTS.items():
        sval = stored.get(group)
        if isinstance(default, dict) and isinstance(sval, dict):
            merged[group] = {**default, **sval}
        else:
            merged[group] = sval if group in stored else default
    # Preserve any stored-only groups not declared in DEFAULTS.
    for group, sval in stored.items():
        merged.setdefault(group, sval)
    return merged


@router.get("")
def get_settings():
    stored = get_all_settings()
    # Ensure every known group has a value to render (lazy-fill if seed didn't run yet).
    merged = _merge_with_defaults(stored)
    secrets_status = {
        key: bool(os.environ.get(env_var))
        for key, env_var in SECRET_ENV_KEYS.items()
    }
    return {"settings": merged, "secrets_set": secrets_status}


@router.get("/{group}")
def get_group(group: str):
    if group not in DEFAULTS:
        raise HTTPException(404, f"Unknown settings group: {group}")
    return {"group": group, "value": get_setting(group, DEFAULTS[group])}


@router.put("")
def update_settings(body: SettingsUpdate):
    if body.group not in DEFAULTS:
        raise HTTPException(400, f"Unknown settings group: {body.group}")
    if any(secret_key.startswith(f"{body.group}.") for secret_key in SECRET_ENV_KEYS):
        # Reject any payload key that names a secret slot — clients must use env vars.
        for k in body.value:
            if f"{body.group}.{k}" in SECRET_ENV_KEYS:
                raise HTTPException(400, f"{body.group}.{k} is env-only; cannot be set via API")
    # Merge over existing so PUT can be partial.
    current = get_setting(body.group, DEFAULTS[body.group])
    if not isinstance(current, dict):
        current = {}
    merged = {**current, **body.value}
    set_setting(body.group, merged)

    # Picking "merge" as the auto-create reel type implies the merge feature must
    # actually be on — auto-flip merge.enabled so the daemon doesn't silently no-op.
    if body.group == "pipeline" and body.value.get("auto_create_reel_type") == "merge":
        merge_cfg = get_setting("merge", DEFAULTS["merge"])
        if not isinstance(merge_cfg, dict):
            merge_cfg = dict(DEFAULTS["merge"])
        if not merge_cfg.get("enabled"):
            set_setting("merge", {**merge_cfg, "enabled": True})

    return {"group": body.group, "value": merged}
