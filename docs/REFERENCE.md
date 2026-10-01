# Reference

> Technical reference: layout, API, settings keys, scripts, deploy.
> Note: some entries predate the generic taxonomy refactor and still say
> `pillar` / `country` / `city`; the code now uses `category` + `tags`.
> The canonical environment-variable list is [`.env.example`](../.env.example).

## Project goal
Automate the pipeline: Instagram archive + Highlights → Reels → published posts.
Full roadmap: `plan/UPDATES.md`

## Monorepo structure
```
backend/
  config.py               — all env vars + path constants
  db.py                   — Supabase-first / SQLite fallback abstraction
  pipeline/
    download_posts.py     — fetch new IG posts → organized/
    download_highlights.py
    index_content.py      — upsert media rows from manifests (idempotent)
    audio_probe.py        — ffprobe music detection
    classify_groq.py      — Groq gpt-oss-120b pillar/country tagger (new downloads only; migrated 2026-08-22, llama-3.3-70b-versatile decommissioned by Groq)
    decaption.py          — opt-in: strip burned-in IG captions/watermarks via vendored video-text-remover (YOLO11 detect + OpenCV inpaint on ONNX Runtime); cleans each source clip once, caches result on the media row, re-muxes audio; runs before resize (single) + per-source pre-pass (merge). Default OFF; needs one-time manual setup (1.5.0)
    stock_footage.py      — opt-in: search Pexels/Pixabay for B-roll by country/pillar keyword, download + index as raw media (source="stock") exactly like a manual upload; merge_clips blends it with archive footage automatically, no merge-side changes. Standalone Download-page action, not part of the per-post pipeline chain. Default OFF (1.8.0)
    voiceover.py          — opt-in: edge-tts narration of the caption hook line + word-synced burned subtitles from the same synthesis pass (no separate transcription); caches voiceover_path/voiceover_srt_path on the media row; runs after caption, before edit. Default OFF; needs one-time manual Supabase migration (1.8.0)
    resize_clips.py       — FFmpeg 9:16 crop
    merge_clips.py        — cinematic country montage: 15+ rapid 1.5-3s cuts spread across 10+ source videos (same country, mixed cities/pillars), several sub-shots per clip INTERLEAVED (same-video cuts never adjacent) → Ken Burns + slow-mo + varied xfades + beat-sync, optional OpenMontage film grade + grain + vignette (skips LUT when graded), mux one mood-matched music bed → 30-45s reel; scratch segments auto-deleted (1.2.2). CPU-only quality pass (1.7.0): cv2 smart sub-shot selection, per-segment gray-world color-match + deblock, deband, eased Ken Burns, hard-cuts-on-beat, opt-in minterpolate slow-mo + nlmeans denoise. Intro/cast overlay + LUT added downstream in video_edit (no added time)
    caption_gen.py        — Groq (openai/gpt-oss-120b) primary, OpenRouter (google/gemma-4-31b-it:free) fallback, generate + refine (always EN+AR; migrated 2026-08-22)
    screens.py            — intro/cast screen builders + concat_screens (prepend/append to reel)
    editor_edl.py         — EDL v1 (user doc) + PLAN v1 (compile artifact) pydantic models; hydrate(media row → EDL), compile(EDL → PLAN + EditOverrides). compile() is the security boundary: path containment, enum whitelists, clamps, DoS caps (2.0.0)
    editor_proxy.py       — content-addressed 480p editor proxies in EDITOR_DIR (sibling of MERGE_DIR so merge cleanup can't delete them), 2-worker encode pool, TTL sweep (2.0.0)
    editor_layers.py      — EDL overlay layers → FFmpeg filters. Text via drawtext `textfile=` (never `text=`, so user strings never enter the filtergraph); images via scale+colorchannelmixer+overlay, paths passed as `-i` argv only. Normalized 0-1 CENTRE coords → overlay `x*W-w/2` expressions so preview and render agree (2.0.0)
    orchestrator.py       — stage chainer with retry + notifications
    scheduler.py          — multi-platform publish library (enqueue/publish/cancel/reschedule)
    youtube_publish.py    — YouTube Shorts uploader (Data API v3, OAuth2 refresh token)
    tiktok_publish.py     — TikTok Direct Post (PULL_FROM_URL or FILE_UPLOAD)
    daemon.py             — APScheduler auto-publish job (starts in FastAPI lifespan)
    telegram_bot.py       — full manager bot (preview push + /create state machine)
  api/
    main.py               — FastAPI app, lifespan, CORS, static mounts
    auth.py               — Supabase JWT verify_token dependency
    ws.py                 — WebSocket broadcast helpers
    routes/
      media.py            — GET/PUT/DELETE /api/media
      posts.py            — CRUD + approve/reject/reschedule/create
      pipeline.py         — trigger pipeline stages via HTTP
      analytics.py        — overview/pillars/timeseries
      captions.py         — caption history
      downloads.py        — trigger download scripts + stock/status, stock/search, stock/import (1.8.0)
      notifications.py    — notification CRUD + IG token status
      settings.py         — grouped settings CRUD + seed
      assets.py           — music + LUT browser + fonts/intros/outros; unified `assets` table CRUD + Storage reconcile (1.10.0)
      edit.py             — AI edit dispatch (OpenRouter tool-use)
      editor.py           — reel editor: EDL hydrate/save/versions/proxies/export + signed proxy stream (2.0.0)
      taxonomy.py         — distinct country/city/pillar for /create flow
      telegram.py         — webhook receiver + debug endpoint
frontend/                 — React + Vite + shadcn/ui
  src/
    pages/
      Design.tsx          — Design page (Video Branding · Intro Screen · Cast Screen tabs)
      Create.tsx          — Single | Merge mode wizard; Merge = country-driven multi-clip montage (city/pillar optional, AND-filtered) with live video-availability indicator (1.2.3); Customize step after filters: preview picked clip + re-pick (single) + optional music/LUT pick, both applied at edit stage (1.6.0)
      Library.tsx         — media grid/list with Preview eye button
      Queue.tsx           — approve/reject/reschedule + live WS countdown
      Preview.tsx         — fullscreen player + side panel + edit drawer; "Edit timeline" opens the reel editor (2.0.0)
      Editor.tsx          — /editor/:mediaId timeline editor (lazy-loaded); Remotion player + dnd-kit timeline + Clip/Text/Image/Colour/Audio inspector tabs + export bar with version History (2.0.0)
      Settings.tsx        — grouped settings form with secrets status
      Analytics.tsx
      Pipeline.tsx
      Downloads.tsx       — Overview · Funnel · By Country · Upload · Google · Stock tabs (1.8.0)
      Assets.tsx          — admin page for Music/Fonts/LUTs/Intros/Outros; card grid + rename/delete + sync preview/confirm, shared search/sort/favourite/tag-chip toolbar across all 5 tabs (1.10.0); absorbed the standalone Audio page — /audio redirects here (?type=music), Music tab adds the dedup Refresh flow alongside Sync (1.12.0)
      Login.tsx
    components/
      CountdownTimer.tsx  — live setInterval ticker (pulses red < 5 min)
      MusicPicker.tsx     — track browser from /api/assets/music
      LutPicker.tsx       — chip picker from /api/assets/luts
      StockImportPanel.tsx — Pexels/Pixabay search → thumbnail grid → import, mirrors GoogleImportPanel (1.8.0)
      audio/TrackCard.tsx — track card (play/favourite/tag/trim) + WaveformTrimModal (numeric nudge, loop-preview, zoom, fade in/out), used by Assets.tsx Music tab (1.12.0)
    lib/
      api.ts              — fetch wrapper (reads VITE_API_BASE_URL)
      ws.ts               — WebSocket client (auto-reconnect, event listeners)
      settings.ts         — useSettings() hook
assets/
  music/                  — cached local tracks (served at /static/assets/music/ in dev)
  luts/                   — .cube color grade files
  stickers/               — PNG/WebP overlay assets for the reel editor's image layers; ships empty, filled by upload (2.0.0)
deploy/
  caddy-social-media-cms.snippet
  social-media-cms.service
  deploy.sh
  rollback.sh
.github/workflows/
  release.yml             — backend CI → VPS (tag vX.Y.Z on release/*)
  frontend-release.yml    — frontend CI → Vercel (tag fe-vX.Y.Z on release/frontend/*)
```

## API endpoints (53 total)

```
GET  /api/health                        scheduler status + telegram mode
GET  /api/media                         ?status= &pillar= &country= &limit= &offset=
GET  /api/media/count                   ?country= &city= &pillar= → {count} raw VIDEO clips available for a merge (images excluded); drives Create-page availability indicator (1.2.3)
GET  /api/media/{id}
PUT  /api/media/{id}
DEL  /api/media/{id}
POST /api/media/{id}/reprocess

GET  /api/posts                         ?status= &media_id= &limit=
POST /api/posts                         create post record
POST /api/posts/select-preview          dry-run: pick a raw clip by strategy/filters (no processing) → {media_id,local_path,country,city,pillar,duration_s}; powers Create-wizard clip preview + re-pick via exclude_ids (1.6.0)
POST /api/posts/create                   pick raw clip by filter → pipeline → enqueue; optional media_id (lock previewed clip), music_path (served URL under MUSIC_DIR) + lut (LUTS_DIR-relative .cube) applied at edit stage; keep_original_audio / no_lut (manual "keep original" when nothing picked) + decaption (per-run on/off override) + voiceover (per-run on/off override, 1.8.0) — all default to the auto behavior so the timer/daemon flow is unchanged (1.6.0)
POST /api/posts/create-merge            hand-pick media_ids OR auto (country REQUIRED, city/pillar/count optional → auto-count) → merge_clips → edit/upload → enqueue; overrides.music_path must resolve under MUSIC_DIR (1.2.0); overrides.lut rides edit tail, overrides.audio_mode=original keeps clips' own audio, decaption per-run override (1.6.0), voiceover per-run override (1.8.0)
POST /api/posts/auto-schedule
PUT  /api/posts/reorder
PUT  /api/posts/{id}
DEL  /api/posts/{id}
POST /api/posts/{id}/approve            sets publish_after=now, daemon publishes next tick
POST /api/posts/{id}/reject
POST /api/posts/{id}/reschedule         body: {scheduled_at, window_minutes}
POST /api/posts/{id}/publish            alias for approve
POST /api/posts/{id}/edit               OpenRouter tool-use → dispatch stages async
POST /api/posts/{id}/retry-youtube      re-upload to R2 if needed, then retry YT Short upload

GET  /api/settings                      all groups + secrets_set map
GET  /api/settings/{group}
PUT  /api/settings                      body: {group, value} — partial merge

GET  /api/taxonomy/countries
GET  /api/taxonomy/cities               ?country=
GET  /api/taxonomy/pillars

GET  /api/series                        all series + posted/total progress + next episode (0.6.0)

GET  /api/assets/fonts                  scan assets/fonts/ for branding-overlay font files
GET  /api/assets/luts
GET  /api/assets/music                  ?q= (Pixabay) + local cached tracks
GET  /api/assets/intros                 list uploaded intro/splash screen assets
POST /api/assets/intros/upload          upload intro asset (mp4/mov/m4v/jpg/png, 50 MB cap)
GET  /api/assets/outros                 list uploaded cast/outro screen assets
POST /api/assets/outros/upload          upload outro asset (mp4/mov/m4v/jpg/png, 50 MB cap)
GET  /api/assets/stickers               list PNG/WebP overlay assets for the editor's image layers; each item carries the ASSETS_DIR-relative `asset` an EDL ImageLayer stores (2.0.0)
POST /api/assets/stickers/upload        upload a sticker (png/webp, 10 MB cap) (2.0.0)
GET  /api/assets/all                    ?type= &favourite= &pillar= &tag= → unified list from the `assets` table (music/font/lut/intro/outro); falls back to local scan when Supabase Storage isn't configured (1.10.0; favourite/pillar/tag filters + local_path field 1.11.0)
GET  /api/assets/all/{id}
PUT  /api/assets/all/{id}               patch name/meta/favourite/tags/pillars on an assets row (favourite/tags/pillars 1.11.0)
DEL  /api/assets/all/{id}               removes the DB row + Storage object; never touches the local file (1.10.0)
POST /api/assets/sync                   ?type= &confirm= → two-step reconcile of local disk + Storage bucket + DB rows, same preview/confirm UX as /api/audio/refresh (1.10.0)

GET  /api/analytics/overview
GET  /api/analytics/pillars
GET  /api/analytics/pillars/performance   realized engagement per pillar 0-1 (Enh I what-works signal)
GET  /api/analytics/timeseries
GET  /api/analytics/hashtags             A/B variant reach + engagement report

GET  /api/captions/{media_id}
POST /api/captions/generate

GET  /api/notifications
PUT  /api/notifications/read-all
GET  /api/notifications/token-status
PUT  /api/notifications/{id}/read

GET  /api/downloads/status
POST /api/downloads/posts
POST /api/downloads/highlights
GET  /api/downloads/check-new
POST /api/downloads/resume
POST /api/downloads/upload                multipart: files[] + meta JSON [{country,city,pillar}] → save to organized/uploads/<country>/<city>/, ffprobe-verify, index as raw media (0.9.12)
POST /api/downloads/upload-url            body {url,country,city,pillar} → server-side fetch public Drive/Dropbox/direct link → index as raw media; SSRF-guarded, gated by uploads.url_fetch (0.9.12)
GET  /api/downloads/google/status         whether Google Drive/Photos import is configured (GOOGLE_* creds in .env) (1.0.2)
GET  /api/downloads/google-drive/list      ?q= &page_token= → owner's Drive video files (single-account OAuth) (1.0.2)
POST /api/downloads/google-drive/import    body {file_id,name,country,city,pillar} → server-side Drive download → index as raw media (1.0.2)
POST /api/downloads/google-photos/session  create a Google Photos Picker session → {id, picker_uri, poll_interval_ms} (1.0.2)
GET  /api/downloads/google-photos/session/{id}  poll session; media_items_set flips true once user finishes picking (1.0.2)
POST /api/downloads/google-photos/import   body {session_id,country,city,pillar} → download every picked video → index as raw media (1.0.2)
GET  /api/downloads/stock/status          whether a Pexels/Pixabay API key is configured (1.8.0)
GET  /api/downloads/stock/library         per-country imported-stock breakdown (count/size + per-clip provider/dims/duration/size/tags) + imported_keys for search-grid dedup (1.8.0)
GET  /api/downloads/stock/search          ?query= &country= &city= &pillar= &provider= → filtered candidate clips (no download yet); gated by stock.enabled (1.8.0)
POST /api/downloads/stock/import          body {id,provider,country,city,pillar} → download + index one searched candidate as raw media (source="stock"); gated by stock.enabled (1.8.0)
DEL  /api/downloads/stock/{media_id}      hard-delete one imported stock clip — remove the file from disk AND the media row (frees storage; source="stock" rows only) (1.8.1)

GET  /api/editor/{media_id}             latest saved EDL, else one hydrated from the media row → {edl, approx, version, project_id, saved_at} (2.0.0)
PUT  /api/editor/{media_id}             body {edl, label?} → persist a new EDL version; history pruned to editor.keep_versions (2.0.0)
GET  /api/editor/{media_id}             ?fresh=1 → skip saved versions and re-hydrate from the media row ("revert to original"; history is left intact) (2.0.0)
GET  /api/editor/{media_id}/versions    version list without the docs (picker only) (2.0.0)
GET  /api/editor/{media_id}/versions/{version}  one saved version WITH its doc — what the History picker loads (2.0.0)
POST /api/editor/{media_id}/proxies     body {edl?} → start 480p proxy encode; progress over WS, completion carries {cut_id: signed_url} (2.0.0)
POST /api/editor/{media_id}/export      body {edl, label?} → compile (400s on an invalid doc) then render/edit/upload in the background; produces a NEW media row and repoints the post (2.0.0)
GET  /api/editor/proxy/{key}.mp4        public, HMAC-signed, Range-capable proxy stream — a <video> tag can't send an Authorization header; fails closed with no EDITOR_MEDIA_SECRET (2.0.0)

GET  /api/pipeline/runs
POST /api/pipeline/orchestrate
POST /api/pipeline/full
POST /api/pipeline/{stage}

POST /api/telegram/webhook/{secret}    Telegram update receiver (HMAC path check)
GET  /api/telegram/webhook-info        debug proxy

WS   /ws/pipeline                      real-time events
```

## Settings keys

```
approval.auto_post_after_minutes   int     default 60
approval.require_manual_for_pillars list   default []
schedule.daily_slots               list    default ["08:00","11:00","14:00","18:00","21:00"] covers IG peak 11-18 window
schedule.timezone                  string  default "Asia/Beirut"
schedule.max_per_day               int     default 3
ai.classifier_model                string  "groq/openai/gpt-oss-120b"   was groq/llama-3.3-70b, decommissioned by Groq 2026-06-17 (2.0.3)
ai.caption_model                   string  "groq/openai/gpt-oss-120b"   caption primary (Groq); was openai/gpt-oss-20b:free (2.0.3), Groq/OpenRouter order swapped (2.0.4)
ai.refine_model                    string  "google/gemma-4-31b-it:free"   OpenRouter fallback model; was meta-llama/llama-3.3-70b-instruct:free (2.0.3, not actually free), then this (2.0.4)
telegram.mode                      string  "poll" | "webhook"
telegram.chat_id                   string
telegram.preview_push_enabled      bool    true
telegram.always_preview            bool    true    push rich preview at creation even in auto-publish mode (1.3.0)
telegram.rich_publish_notify       bool    true    post-publish daemon notification loads media + full details + link (1.3.0)
telegram.admin_controls            bool    true    show extended admin buttons (Edit/Details/Reschedule menu) on preview (1.3.0)
music.preferred_source             string  "licensed"
music.pixabay_query                string  "travel cinematic"
music.swap_on_detect_original      bool    false
music.mood_match                   bool    true    pick music by caption-derived mood (Enh G)
pillars.taxonomy                   list    ["hidden_gem","budget","culture","nature","food","beach"]
platforms.youtube_enabled          bool    false
platforms.tiktok_enabled           bool    false
caption.use_feedback               bool    true    inject top-performing hooks into generator (Enh A)
caption.self_critique              bool    true    extra OpenRouter hooks-only refine pass (Enh J)
caption.use_trends                 bool    true    inject weekly Google-Trends travel topics (Enh B)
schedule.optimize_times            bool    true    order free slots by historical engagement (Enh C)
caption.draft_with_groq            bool    false   draft on free Groq, polish on OpenRouter — cost→~$0 (Enh L)
caption.use_hook_library           bool    true    inject viral hook templates (per pillar + arc) into caption prompt (0.9.10)
caption.trends_geo                 bool    true    geo-target Google Trends to clip's country (0.9.10)
caption.hook_templates             list    []      user-supplied hook strings; empty = built-in library (0.9.10)
caption.cta_style              string  "send"   last-line CTA style: "send" (named-persona send prompt — highest cold-reach signal) | "save" (save-worthy) | "follow" (follow CTA); default send per Mosseri sends-per-reach hierarchy (1.3.0)
hashtags.ab_test                   bool    true    coin-flip hashtags_en vs hashtags_en_b per post (Enh D)
hashtags.blocked                   list    []      shadow-ban/over-saturated tags stripped from sets; empty = built-in denylist (Enh L)
hashtags.curated_enabled           bool    true    blend curated viral pool tags with LLM tags per post (0.9.10)
hashtags.blend_count               int     3       curated pool tags per post (3 reach + 2 LLM niche = 5-tag IG cap); rotated by post seq (0.9.10)
hashtags.pools                     dict    {}      per-platform curated pools {instagram/tiktok/youtube:[...]}; empty = built-in defaults (0.9.10)
monetize.enabled                   bool    false   append CTA text to caption body before hashtags (0.9.10)
monetize.cta_text                  string  ""      CTA line appended to configured platforms (e.g. "Full guide & links in bio") (0.9.10)
monetize.youtube_link              string  ""      clickable link appended to YouTube description only (0.9.10)
monetize.platforms                 list    ["instagram","tiktok","youtube"]   platforms that receive CTA injection (0.9.10)
vision.enabled                     bool    true    run classify_vision hook-scoring stage (Enh E)
vision.provider                    string  "auto"  nightly 03:00 backfill provider: "auto" | "groq" | "local" (0.9.9)
vision.nightly_limit               int     50      max un-scored clips per nightly 03:00 vision backfill run (0.9.9)
selection.use_performance          bool    true    blend realized pillar engagement into clip pick (Enh I)
selection.performance_weight       float   0.5     how hard proven pillars lift hook_score in selection (Enh I)
selection.min_duration_s           float   10.0    reject clips shorter than this at selection (0.6.0)
selection.min_short_side           int     720     reject clips below this short-edge px; 0=off (0.6.0)
selection.min_hook_score           float   0.0     reject below this predicted hook score; 0=off (0.6.0)
selection.require_video_only       bool    true    only pick VIDEO media (images/carousels can't be Reels) (0.6.0)
selection.quality_probe_enabled    bool    true    run FFmpeg blur/shake probe as first pipeline stage (0.6.0)
selection.min_quality_score        float   0.0     reject below this 0-1 probe score; 0=measure-only (0.6.0)
selection.require_classified       bool    true    only pick clips with pillar+hook_score+country set; falls back if pool would be empty (0.7.0)
selection.country_cooldown_countries int   20      skip a country until this many OTHER distinct countries posted since; 0=off; used by diverse strategy AND merge auto-country pick; "Unknown Location" always excluded from auto-pick (0.7.0)
video.enhance_quality              bool    true    master toggle for free FFmpeg quality chain at edit stage (Enh K)
video.denoise                      bool    true    hqdn3d denoise before motion (Enh K)
video.denoise_strength             string  "light" light | medium | strong (Enh K)
video.sharpen                      bool    true    contrast-adaptive sharpen (cas) after LUT (Enh K)
video.sharpen_amount               float   0.4     cas strength 0.0–1.0 (Enh K)
video.crf                          int     20      x264 quality (lower=sharper); was 22 (Enh K)
video.preset                       string  "medium" x264 preset balancing quality vs CPU cap (Enh K)
video.smooth_motion                bool    false   minterpolate frame-interp, CPU-heavy, opt-in (Enh K)
video.smooth_fps                   int     60      target fps when smooth_motion on (Enh K)
color.lut_mode                     string  "pillar" content-aware LUT pick: "pillar" | "mood" | "vision" | "fixed" (0.9.7)
color.fixed_lut                    string  ""      LUTS_DIR-relative .cube applied to every reel when lut_mode=fixed (0.9.7)
color.use_vision                   bool    false   allow AI-vision LUT override (reuses classify_vision; adds a Groq call) (0.9.7)
color.intensity                    float   1.0     advisory grade strength 0.0–1.0; full LUT applied (no opacity blend in v1) (0.9.7)
intro.enabled                      bool    false   overlay a transparent splash card (text + bg_opacity tint) over the first intro.duration_s of every reel — live video plays underneath, no added time (0.9.0; transparent overlay 1.2.3)
intro.mode                         string  "generated"  "generated" (text card) | "asset" (uploaded file) (0.9.0)
intro.asset_file                   string  ""      filename in assets/intros/ when mode=asset (0.9.0)
intro.duration_s                   float   2.0     intro hold duration in seconds 1.0–4.0 (0.9.0)
intro.animation                    string  "fade"  "none" | "fade" | "zoom" (0.9.0)
intro.show_handle                  bool    true    show ig_handle from branding settings on intro (0.9.0)
intro.show_location_title          bool    true    show "City · Pillar" from media metadata (0.9.0)
intro.show_hook                    bool    false   burn caption hook line as bold headline on intro overlay — first-frame SEO + retention lever (1.3.0)
intro.hook_source                  string  "caption_line1"  source for hook text: "caption_line1" | "manual" (1.3.0)
intro.hook_text                    string  ""      custom hook text when hook_source=manual (1.3.0)
intro.hook_color                   string  "#ffffff"  hook headline text color (1.3.0)
intro.hook_font                    string  ""      font filename for hook headline; empty = PlayfairDisplay (1.3.0)
intro.hook_font_size               int     56      hook headline font size px (1.3.0)
intro.hook_order                   int     -1      rendering order; -1 = before all other intro elements (1.3.0)
intro.hook_bottom_padding          int     24      space below hook headline in px (1.3.0)
intro.bg_color                     string  "#000000"  intro background color (0.9.0)
intro.bg_opacity                   float   0.15    tint opacity 0.0–1.0 over the live video; default 0.15 (lighter tint preserves visual hook) (0.9.0)
intro.text_color                   string  "#ffffff"  intro text color (0.9.0)
intro.font                         string  ""      font filename from assets/fonts/; empty = PlayfairDisplay (0.9.0)
cast.enabled                       bool    false   overlay a transparent cast/outro card over the last cast.duration_s of every reel — live video plays underneath, no added time (0.9.0; transparent overlay 1.2.3)
cast.mode                          string  "generated"  "generated" | "asset" (0.9.0)
cast.asset_file                    string  ""      filename in assets/outros/ when mode=asset (0.9.0)
cast.duration_s                    float   2.5     cast hold duration in seconds 1.0–5.0 (0.9.0)
cast.animation                     string  "fade"  "none" | "fade" | "zoom" (0.9.0)
cast.cta_text                      string  "Follow for more"  call-to-action line on cast screen (0.9.0)
cast.show_location_recap           bool    true    restate location on cast screen (0.9.0)
cast.show_next_episode             bool    true    show next-episode hint for series content (0.9.0)
cast.minimal_cta                   bool    false   when true + cta is send-prompt, suppress all other cast elements for clean closing beat (1.3.0)
cast.bg_color                      string  "#000000"  cast background color (0.9.0)
cast.bg_opacity                    float   0.15    tint opacity 0.0–1.0 over the live video; default 0.15 (lighter tint preserves visual hook) (0.9.0)
cast.text_color                    string  "#ffffff"  cast text color (0.9.0)
cast.font                          string  ""      font filename from assets/fonts/; empty = PlayfairDisplay (0.9.0)
branding.overlay_enabled           bool    false   opt-in: bake branded bar with location + @handle onto every reel + thumbnail (0.7.0); configure via Design page
branding.ig_handle                 string  ""      your @handle shown on bar; empty = overlay skipped (0.7.0)
branding.font_size                 int     0       font size in px for bar text; 0 = auto (proportional to bar_height) (0.8.0)
branding.bar_height                int     45      bar height in px; font scales proportionally (0.7.0)
branding.show_on_thumbnail         bool    true    apply same bar to the R2 thumbnail image (0.7.0)
branding.bar_bg_color              string  "#ffffff"  bar background as CSS hex color (0.7.0)
branding.text_color                string  "#000000"  location + handle text color as CSS hex (0.7.0)
branding.bar_opacity               float   1.0     bar bg opacity 0.0–1.0; text always fully opaque (0.7.0)
branding.bar_position              string  "bottom"   "bottom" | "top" — which edge of the frame (0.7.0)
branding.location_side             string  "left"  which side of bar the location text sits on (0.7.0)
branding.handle_side               string  "right" which side of bar the @handle sits on (0.7.0)
uploads.max_mb                     int     500     per-file size cap for manual video uploads (local + URL fetch) (0.9.12)
uploads.allowed_types              list    [".mp4",".mov",".m4v",".webm"]   accepted upload extensions (0.9.12)
uploads.auto_probe                 bool    true    ffprobe duration/dimensions right after upload so selection gates work (0.9.12)
uploads.url_fetch                  bool    true    allow server-side URL-paste fetch (Drive/Dropbox/direct); SSRF-guarded (0.9.12)
merge.enabled                      bool    false   master gate for the multi-clip merge feature (1.1.0)
merge.auto_run                     bool    false   build a merged reel inside the normal create flow instead of a single clip (1.1.0)
merge.clips_per_reel               int     4       fallback clip count when auto_count off; clamped 2–8 (1.1.0)
merge.target_duration_s            float   30.0    target merged reel length; clamped 20–60 (1.2.0)
merge.selection_strategy           string  "diverse"  auto-select pick: "best" | "diverse" | "random" (1.1.0)
merge.scene_aware                  bool    true    PySceneDetect best sub-shot per clip; off = trim from start (1.1.0)
merge.transition                   string  "fade"  xfade transition enum (fade/dissolve/wipeleft/slideup/…) (1.1.0)
merge.transition_ms                int     500     crossfade duration in ms; clamped 100–1500 (1.1.0)
merge.beat_sync                    bool    true    librosa beat-aligned cuts; default-on, lazy-imported (1.2.0)
merge.min_clip_score               float   0.0     reject clips below this quality_score before merge; 0=off (1.1.0)
merge.cut_min_s                    float   1.5     min per-cut segment length; rapid montage cut, not the whole clip (1.2.1)
merge.cut_max_s                    float   3.0     max per-cut segment length; clamped to cut_min..12 (1.2.1)
merge.min_segments                 int     20      auto-count floor: montage never has fewer cuts/scenes than this; clamped 15–30 (raised 15→20 in 1.8.1)
merge.min_main_videos              int     10      best-effort: spread cuts across >=this many source videos; small pool uses all; clamped 2–20 (1.2.2)
merge.split_stock_local            bool    true    auto-select only: pull a floor of stock B-roll AND local-archive clips per montage; a thin pool on one side tops up from the other (1.8.1)
merge.min_stock_segments           int     8       min stock (Pexels/Pixabay) clips per merged reel when split_stock_local on; per-run overridable in the Create merge wizard (1.8.1)
merge.min_local_segments           int     12      min local-archive clips per merged reel when split_stock_local on; per-run overridable in the Create merge wizard (1.8.1)
merge.auto_fetch_stock             bool    false   opt-in: when the merge country has NO stock yet, download a few clips per provider on the fly so the montage can blend them; needs stock.enabled + a provider key (1.8.1)
merge.auto_fetch_pexels            int     3       clips pulled from Pexels when auto_fetch_stock fires (1.8.1)
merge.auto_fetch_pixabay           int     3       clips pulled from Pixabay when auto_fetch_stock fires (1.8.1)
merge.segments_per_clip            int     3       distinct non-overlapping sub-shots pulled per source video (clamped 1–4); same-video cuts interleaved, never back-to-back (1.2.1)
merge.cleanup_segments             bool    true    delete the per-merge scratch dir of trimmed segments after render; final reel kept (1.2.1)
merge.grade                        string  ""      OpenMontage film-look grade on the whole montage (cinematic_warm/cool/moody_dark/bright_clean/vintage_film/high_contrast/neutral); ""=off; when set the downstream LUT is skipped for merged reels (1.2.2)
merge.grain                        bool    false   subtle film grain (noise) texture over the montage (1.2.2)
merge.vignette                     bool    false   darken frame edges for a filmic vignette (1.2.2)
merge.auto_count                   bool    true    derive clip count from target_duration ÷ avg cut (floor=min_segments, ceil=30); off = use clips_per_reel (1.2.1)
merge.audio_mode                   string  "music" "music" = one mood-matched bed (sources muted) | "original" = longest clip's own audio (1.2.0)
merge.music_fade_s                 float   1.0     music bed fade in/out seconds; clamped 0–5 (1.2.0)
merge.slow_motion                  bool    true    duration-preserving slow-mo (setpts+trim) on alternating segments (1.2.0)
merge.slow_motion_factor           float   0.85    slow-mo PTS factor <1.0 = slower; clamped 0.3–1.0 (1.2.0)
merge.ken_burns                    bool    true    gentle zoompan push/pull per segment (1.2.0)
merge.transition_variety           bool    true    rotate fade/dissolve/slideup/wipeleft/smoothleft/circleopen across cuts (1.2.0)
merge.loop_friendly                bool    false   echo opener as last cut + skip music fade-out → seamless TikTok/IG loop (1.3.0)
merge.adaptive_fx                  bool    true    per-clip content-adaptive FX: each clip's duration (by quality) + slow-mo (calm clips) + Ken Burns (low-motion) + denoise (dark/noisy) + sharpen (soft) decided from its own cv2 metrics; off = fixed idx-parity rules (1.7.0)
merge.smart_select                 bool    true    cv2 aesthetic scoring (sharpness/exposure/motion + histogram variety) picks the best sub-shot per clip instead of longest; falls back to longest-scene w/o cv2 (1.7.0)
merge.select_sharpness_weight      float   0.5     weight of sharpness in the sub-shot score 0–1 (1.7.0)
merge.select_min_sharpness         float   0.0     reject sub-shots below this normalized sharpness 0–1; 0=off (1.7.0)
merge.color_match                  bool    true    gentle per-segment gray-world white-balance nudge (±12%) so mixed clips don't jump cut-to-cut (1.7.0)
merge.deband                       bool    true    anti-banding pass after grade (kills sky/gradient banding); cheap (1.7.0)
merge.hard_cuts_on_beat            bool    true    mix ~1-frame hard cuts among crossfades (every 3rd join) for punchier rhythm (1.7.0)
merge.smooth_slowmo                bool    false   minterpolate motion-compensated slow-mo (judder-free) — CPU-HEAVY 2–5×; default off (1.7.0)
merge.smooth_slowmo_max_s          float   3.0     only interpolate slowed segments up to this length (s) to cap cost (1.7.0)
merge.deblock                      bool    true    deblock IG-compression artifacts per segment; cheap (1.7.0)
merge.sharpen                      bool    false   per-segment contrast-adaptive sharpen (cas); off by default to avoid double-sharpen with video.sharpen (1.7.0)
merge.sharpen_amount               float   0.3     cas strength 0–1 when merge.sharpen on (1.7.0)
merge.strong_denoise               bool    false   nlmeans strong denoise for grainy clips — CPU-HEAVY; default off (1.7.0)
merge.dedupe_enabled               bool    true    anti-repeat: same-country reels avoid sub-shots recent reels used (metadata-only memory in the mrg_ row's cuts; no cache/migration); first reel unchanged (1.7.0)
merge.subshot_cooldown_reels       int     3       hard-exclude a used sub-shot for the last N same-country reels; past N it's soft-weighted; clamped 0–20 (1.7.0)
merge.dedupe_soft_weight           float   0.5     selection-score multiplier for reused sub-shots past the cooldown; clamped 0–1 (1.7.0)
merge.proven_topup                 bool    true    top up a thin fresh pool with the highest-scoring previously-used sub-shots (re-cut on demand) rather than under-filling (1.7.0)
merge.proven_min_score             float   0.5     only reuse a previously-used sub-shot for top-up if its aesthetic score ≥ this; clamped 0–1 (1.7.0)
merge.dynamic_count                bool    true    scale cut count to the country's footage + maximize DISTINCT clips (one cut/clip when the pool allows); off = fixed min_segments/clips_per_reel (1.7.0)
merge.max_cuts_per_source          int     1       max cuts from one source clip before reusing one; 1 = max variety, relaxed on small pools so the reel still fills; 0 = auto; clamped 0–8 (1.7.0)
decaption.enabled                  bool    false   master gate: strip burned-in IG captions/watermarks from source clips before resize/merge (1.5.0)
decaption.algorithm                string  "hybrid" OpenCV inpaint method: "hybrid" | "telea" | "ns" (1.5.0)
decaption.detect_mode              string  "auto"  text-region source: "auto" (YOLO11) | "bottom" | "top" | "custom" (1.5.0)
decaption.custom_bbox              string  ""      "x,y,w,h" inpaint region when detect_mode=custom (1.5.0)
decaption.min_confidence           float   0.35    YOLO11 detection confidence threshold 0.0–1.0 (1.5.0)
decaption.dilate_px                int     6       expand mask around detected text before inpaint (1.5.0)
decaption.fallback                 string  "blur"  on inpaint failure: "blur" | "fill" | "none" (1.5.0)
stock.enabled                       bool    false   master gate: search Pexels/Pixabay for B-roll and index results as raw media alongside your archive (1.8.0). Downloads the ~720p HD rendition (never 4K) to save storage (1.8.1)
stock.source                        string  "pexels" provider(s) to search: "pexels" | "pixabay" | "both" (1.8.0)
stock.per_pillar_query              dict    {}      override the built-in search phrase per pillar; empty = built-in cinematic travel phrases (1.8.0)
stock.max_clips_per_search          int     5       results fetched per search call (1.8.0)
stock.min_short_side                int     720     reject candidate clips below this short-edge px; 0=off (1.8.0)
stock.min_duration_s                float   5.0     reject candidate clips shorter than this (1.8.0)
voiceover.enabled                   bool    false   master gate: edge-tts narration of the caption hook line + burned word-synced subtitles (1.8.0)
voiceover.voice                     string  "en-US-AriaNeural"  edge-tts voice id (1.8.0)
voiceover.rate                      string  "+0%"   edge-tts speaking-rate adjustment (1.8.0)
voiceover.narration_source          string  "caption_hook"  "caption_hook" (first line of generated caption) | "manual" (1.8.0)
voiceover.subtitles_enabled         bool    true    burn word-synced subtitles from edge-tts's own timestamps (1.8.0)
voiceover.subtitle_position         string  "bottom"  "bottom" | "top" (1.8.0)
voiceover.subtitle_font_size        int     28      subtitle font size in px (1.8.0)
voiceover.subtitle_color            string  "#ffffff"  subtitle text color (CSS hex) (1.8.0)
editor.enabled                      bool    true    master gate for the /editor route + /api/editor/* (2.0.0)
editor.proxy_height                 int     480     short-edge px of the browser-player proxies (2.0.0)
editor.proxy_ttl_days               int     7       sweep cached proxies older than this (nightly 04:00 daemon job) (2.0.0)
editor.autosave_seconds             int     15      debounced autosave interval in the editor (2.0.0)
editor.keep_versions                int     20      EDL versions retained per reel; older ones pruned on save (2.0.0)
editor.max_text_layers              int     20      per-EDL cap on text overlays (DoS + render cost) (2.0.0)
editor.max_image_layers             int     10      per-EDL cap on image/sticker overlays (2.0.0)
editor.max_cuts                     int     40      per-EDL cap on timeline cuts; matches merge_clips._MAX_CUTS (2.0.0)
editor.export_mode                  string  "overwrite"  "overwrite" (repoint the existing post) | "new_post" (2.0.0)
editor.preview_lut                  bool    true    WebGL 3D-LUT preview in the browser; off = plain video (2.0.0)
voiceover.music_duck_volume         float   0.08    music bed volume while narration plays (below the normal ~0.15 default) (1.8.0)
```

Manual uploads (0.9.12): videos added via the Download page land in `organized/uploads/<country>/<city>/`, are indexed as `status=raw` rows with `source="upload"` and `id="up_<uuid>"`, and flow through the normal create-pipeline. The `uploads/` dir is excluded from the Downloads By-Country funnel (shown in a dedicated Uploads stat instead). URL fetch rejects private/loopback/link-local/metadata IPs before any request.

Decaption (1.5.0): when `decaption.enabled`, the `decaption` stage cleans each source clip once and caches the result on the media row (`decaptioned` flag + `decaptioned_path`), so every future single/merge reel reuses the clean footage. One-time manual setup is required before enabling: run `backend/scripts/setup_decaption.py` (pip-installs onnxruntime/opencv + fetches the YOLO11s weights) and apply the Supabase migration `ALTER TABLE media ADD COLUMN decaptioned INT DEFAULT 0; ALTER TABLE media ADD COLUMN decaptioned_path TEXT;`.

Stock footage (1.8.0): rows imported via the Download page's Stock tab (or the `stock_footage` stage) get `source="stock"` and an `id="stk_<uuid>"`, otherwise indexed identically to a manual upload (same `organized/uploads/<country>/<city>/` path, same funnel exclusion). Requires `PEXELS_API_KEY` and/or `PIXABAY_API_KEY` in `.env`; `stock.enabled` gates both the search/import routes and the standalone `stock_footage` stage.

Stock footage (1.8.1): downloads prefer the ~720p HD rendition (Pexels: largest file ≤720p, else smallest available so never 4K; Pixabay: the 720p "medium" tier). Each imported clip has a Delete button in the Stock-library view (`DEL /api/downloads/stock/{media_id}`) that hard-deletes the file + media row to reclaim storage. Merge reels enforce a stock/local segment quota (`merge.split_stock_local`, default 8 stock + 12 local = ≥20 cuts); a thin pool on one side tops up from the other. `merge.min_segments` floor raised 15→20. When `merge.auto_fetch_stock` is on and the merge's country/pillar has NO stock yet, the run auto-downloads a few clips per provider (default 3 Pexels + 3 Pixabay, pillar→country query) inside `merge_clips.run` before selection, so they're pickable in the same reel; needs `stock.enabled` + a provider key, best-effort (never aborts the merge).

Voiceover (1.8.0): when `voiceover.enabled`, the `voiceover` stage synthesizes narration via `edge-tts` (free, no API key) and caches the result on the media row (`voiceover_path` + `voiceover_srt_path`), reused if already present. One-time manual Supabase migration is required before enabling: `ALTER TABLE media ADD COLUMN voiceover_path TEXT; ALTER TABLE media ADD COLUMN voiceover_srt_path TEXT;`. No model-weight download (unlike decaption) — word-boundary subtitle timing comes directly from edge-tts's own synthesis pass, since the narration text is already known before speech is generated.

Reel editor (2.0.0): `/editor/:mediaId` edits the reel's SOURCE CLIPS, not the finished MP4 — export re-runs `merge_clips.render(plan)` then the `edit`/`upload` tail. The split of ownership is load-bearing: `render()` owns geometry + time (cut order, in/out, joins, per-cut speed/Ken Burns, film grade, music bed) while `video_edit.edit_single(edl_overrides=...)` owns everything composited on top in one encode (eq, LUT, text layers, image layers, branding, subtitles, intro/cast) — which is why a text- or sticker-only change re-runs the composite pass alone in seconds instead of re-merging. Export always writes a NEW media row and repoints the post at it, keeping its schedule/slot/caption; the parent reel is never mutated. Reels merged from 2.0.0 on persist `metadata.merge.plan` and round-trip exactly; older ones are reconstructed from the legacy `metadata.merge.cuts` spine and flagged `approx: true` in the UI. Needs `EDITOR_MEDIA_SECRET` (falls back to `SUPABASE_JWT_SECRET`) for the signed proxy stream, migration `016_edit_projects.sql` applied manually, and `python -m backend.scripts.make_lut_previews` run once for the WebGL LUT preview.

Secrets (`TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_ACCESS_TOKEN`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`) stay in `.env` only — never in the settings table. Settings UI shows `secrets_set: {key: bool}` only.

## DB state machine
```
raw → resized → edited → uploaded → scheduled → preview → posted
                                                         ↘ error (any stage)
```

Post approval flow:
- Created with `status=preview`, `publish_after = scheduled_at + window`
- Daemon checks every 60 s: `publish_after <= now AND status=preview` → auto-publish
- Approve endpoint: sets `publish_after=now` → daemon picks up on next tick
- Reject: `status=rejected`

## Running pipeline scripts

```bash
# Index local archive (idempotent)
python -m backend.pipeline.index_content

# Classify new downloads (Groq — rate-limited)
python -m backend.pipeline.classify_groq

# Vision hook-scoring (Enh E). Groq primary; local Moondream/Ollama fallback.
# Background backfill on free CPU time: --provider local
python -m backend.pipeline.classify_vision --provider local --limit 50

# Generate caption (EN+AR)
python -m backend.pipeline.caption_gen --country Japan --city Kyoto --pillar culture

# Refine existing caption
python -m backend.pipeline.caption_gen --media-id abc123 --mode refine --feedback "shorter, add cost"

# Full orchestrated pipeline
python -m backend.pipeline.orchestrator --stages index,classify,resize,caption

# Quality probe (0.6.0) — runs auto as first create-pipeline stage. Backfill old
# clips on free CPU time (stores quality_score; flags do_not_use only if
# selection.min_quality_score > 0):
python -m backend.pipeline.quality_probe --backfill

# Flag unusable clips (0.6.0) — permanently shelve raw clips failing the hard
# present-field rules (too short / too low-res). Dry-run first:
python -m backend.pipeline.flag_unusable --dry-run
python -m backend.pipeline.flag_unusable

# Bake .cube LUTs into 2D strip PNGs for the editor's WebGL colour preview
# (2.0.0). Run once after adding LUTs; output is gitignored, so run it on the
# server too. Without it the editor previews eq only, never the LUT.
python -m backend.scripts.make_lut_previews          # only missing/stale
python -m backend.scripts.make_lut_previews --force
```

## Caption output schema (both modes)

```json
{
  "caption":     "English caption ≤2000 chars",
  "caption_ar":  "Arabic caption (natural, not literal)",
  "hashtags_en": ["tag1","tag2","tag3","tag4","tag5"],
  "hashtags_ar": ["وسم1","وسم2","وسم3"],
  "alt_text":    "visual description ≤120 chars"
}
```

`media.caption` stores `EN\n\nAR` combined for the final IG post.

## Telegram bot commands

```
/queue    — upcoming posts
/pending  — posts awaiting approval
/stats    — media counts
/settings — current settings summary
/create   — interactive: country → city → pillar → confirm → pipeline → preview push
/help     — command list
```

Inline buttons on preview:
  Per-platform: 📸 Publish IG · 🎵 Publish TikTok · ▶️ Publish YT (one per enabled platform)
  ✅ Approve All · ✏️ Edit caption · ℹ️ Details · 🕐 Reschedule · 🔄 Regenerate · 🚫 Cancel · ❌ Reject

## Deploy — Backend (VPS)

### First deploy (one-time server prep)
```bash
# On the VPS
mkdir -p /srv/social-media-cms/{data,assets,db,backups,reels,logs}
cp .env /srv/social-media-cms/.env
# Append deploy/caddy-social-media-cms.snippet to host Caddyfile, reload Caddy
# Install systemd unit
cp deploy/social-media-cms.service /etc/systemd/system/
systemctl enable social-media-cms
systemctl start social-media-cms
```

### Release cut (backend)
```bash
git checkout -b release/0.1
git tag v0.1.0
git push origin release/0.1 v0.1.0
# CI builds image → pushes to GHCR → SSHes to the VPS → deploy.sh
```

### Manual rollback
```bash
ssh user@your-server "cd /srv/social-media-cms && bash deploy/rollback.sh v0.1.0"
```

### Register Telegram webhook (after first deploy)
```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<domain>/api/telegram/webhook/<TELEGRAM_WEBHOOK_SECRET>"
```

## Deploy — Frontend (Vercel)

### First setup (one-time)
```bash
cd frontend
vercel link   # link to Vercel project
# Set env vars in Vercel dashboard:
#   VITE_API_BASE_URL=https://social-media-cms.yourdomain.com/api   (Production)
#   VITE_API_BASE_URL=https://staging-api.yourdomain.com/api  (Preview)
#   VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
# Enable Deployment Protection (password) on Production + Preview
```

### Release cut (frontend)
```bash
git checkout -b release/frontend/0.1
git tag fe-v0.1.0
git push origin release/frontend/0.1 fe-v0.1.0
# CI: typecheck → build → vercel deploy --prod
```

### Rollback (Vercel)
```bash
vercel rollback <deployment-url>
# or "Promote to Production" on prior deployment in dashboard
```

## GitHub secrets required

| Secret | Workflow |
|---|---|
| `SSH_PRIVATE_KEY` | backend |
| `DEPLOY_HOST` | backend |
| `DEPLOY_USER` | backend |
| `GHCR_TOKEN` | backend (PAT with `read:packages` — the VPS pulls image from GHCR) |
| `TELEGRAM_BOT_TOKEN` | both (deploy notifications) |
| `TELEGRAM_CHAT_ID` | both |
| `VERCEL_TOKEN` | frontend |
| `VERCEL_ORG_ID` | frontend |
| `VERCEL_PROJECT_ID` | frontend |
| `VITE_API_BASE_URL` | frontend |
| `VITE_SUPABASE_URL` | frontend |
| `VITE_SUPABASE_ANON_KEY` | frontend |

## Key constraints
- Never post same `media_id` twice (check `ig_media_id` in posts table)
- Videos must be at public R2 URL before publishing (`r2_url` field)
- IG access token expires every 60 days — refresh via Meta token refresh endpoint
- All posts get both EN + AR hashtags (`media.caption` = EN\n\nAR combined)
- APScheduler must run in **single uvicorn worker** — `--workers 1` enforced in Dockerfile
- `SUPABASE_SERVICE_KEY` (service-role) required for all backend writes — anon key trips RLS
- `VITE_*` vars are baked into the frontend bundle — never put service-role keys there

