# Release Notes — Social Media Content System

All notable changes to this project are documented here.  
Format: `[version | fe-version] — date` · Backend tag `vX.Y.Z` · Frontend tag `fe-vX.Y.Z`

---
## [Unreleased] — Public open-source release

### Changed
- Taxonomy is now generic: travel-specific `pillar` / `country` / `city` replaced by `category` + `tags` (backend + frontend).
- Licensed under MIT (`LICENSE`).
- Renamed deploy artifacts `travel-cms` → `social-media-cms` (image name, `/srv/social-media-cms`, systemd unit, Caddy snippet, compose network). **Existing deployments:** move `/srv/travel-cms` → `/srv/social-media-cms` and reinstall the systemd unit before the next deploy.
- CORS production origins now come from `CORS_ORIGINS` (comma-separated) instead of a hardcoded domain.
- Landing / Privacy / Terms pages read branding from `VITE_APP_NAME`, `VITE_OPERATOR_NAME`, `VITE_CONTACT_EMAIL`, `VITE_INSTAGRAM_URL`, `VITE_YOUTUBE_URL`, `VITE_TIKTOK_URL`; social buttons hide when their URL is unset.
- Detailed reference moved from `CLAUDE.md` to `docs/REFERENCE.md`; `OLLAMA_INSTALLATION.md` moved to `docs/`.

### Added
- **Demo mode** (`VITE_DEMO_MODE=true`): the frontend runs with no backend or Supabase. A fetch interceptor serves in-memory sample data (`frontend/src/demo/`), auth is faked, WebSocket events are simulated, and a "Live demo" banner is shown. Fixtures are lazy-loaded and excluded from normal builds.
- **Live preview on GitHub Pages**: `.github/workflows/demo-pages.yml` builds the demo on every push to `main` (SPA fallback via `404.html`). `vite.config.ts` honours `VITE_BASE` for sub-path deploys.
- README rewritten: live demo, screenshot gallery + animated GIFs (`docs/screenshots/`), Mermaid architecture/pipeline/lifecycle/approval diagrams, tech stack with versions, full install + usage guide.

### Changed (UI)
- App name and logo initials in the sidebar, login and Docs come from `VITE_APP_NAME` (was hardcoded "Travel CMS"); landing hero and meta description are niche-neutral.
- Category colours: categories outside the pinned map get a stable colour from a palette (`categoryChartColor` / `categoryBadgeColor`) instead of grey.

### Removed
- Commercial fonts (Futura, Gill Sans, Sabon LT, Northwell, Handvetica Neue) are no longer tracked; only open-licensed fonts ship.
- Third-party LUT packs (`assets/luts/cinematic/`) and the music cache are no longer tracked — bring your own (see README).
- Vendored Claude skills (`.claude/`), Supabase CLI temp state, stale planning docs and one-off scripts.

### Fixed
- `requirements.txt`: `httpx2` typo → `httpx`.
- `.env.example` reconciled with `backend/config.py`; `.gitignore` no longer swallows `.env.example`.

---
## [v2.0.3] — 2026-08-22

### Fixed - Caption generation broken: OpenRouter + Groq model slugs decommissioned

Root cause (two separate provider deprecations, both hit in production 2026-08-22):
- OpenRouter pulled `openai/gpt-oss-20b:free` from its free tier (404 "unavailable for free"). Every `caption_gen` call and AI edit-dispatch call failed, triggering the DB fallback path on each run.
- Groq decommissioned `llama-3.3-70b-versatile` for free/developer-tier accounts (announced 2026-06-17). `classify_groq` and the Groq caption drafter (`caption.draft_with_groq`) 404'd with `model_not_found`.

Fixed model slugs and swapped `caption_gen.generate()`'s provider order to Groq
primary / OpenRouter fallback (Groq is free and faster; OpenRouter now only
covers Groq outages):
- `backend/pipeline/classify_groq.py` + `caption_gen.py` Groq calls → `openai/gpt-oss-120b` (Groq's recommended replacement for decommissioned 70B-versatile)
- `backend/config.py` `OPENROUTER_MODEL` → `google/gemma-4-31b-it:free` (meta-llama/llama-3.3-70b-instruct:free, tried first, turned out not to be free either — reverted)
- `caption_gen.generate()`: was OpenRouter→Groq→DB, now Groq→OpenRouter→DB; `refine()`/self-critique stay OpenRouter-only
- `backend/api/routes/settings.py` `ai.*` DEFAULTS updated to match

---
## [v2.0.2] — 2026-08-18

### Fixed - PostgREST select syntax wrong — captions.* invalid (PostgREST doesn't allow table-prefixed *, only plain *)

Root cause: PostgREST rejects table-prefixed * in select (only plain * or aggregate funcs allowed after prefix). Every caption-fallback call failed since 2.0.1, pipeline stopped at caption stage each run. Fixed both queries in `caption_gen.py`

---

## [v2.0.1 | fe-v2.0.1] — 2026-08-17

### Change — AI provider swapped Anthropic → OpenRouter (`feature/openrouter-migration`)

Caption generation/refine (`caption_gen.py`) and AI edit dispatch
(`api/routes/edit.py`) now call OpenRouter's free tier
(`openai/gpt-oss-20b:free`) instead of Anthropic's Claude Haiku, via the
`openai` SDK pointed at `https://openrouter.ai/api/v1`. `edit.py`'s tool-use
dispatch was rewritten from Anthropic's `tools`/`input_schema` block format
to OpenAI-style function calling (`tool_calls[0].function.arguments`).

- `ANTHROPIC_API_KEY` → `OPENROUTER_API_KEY` (`.env`, `config.py`,
  `settings.py` secret map `ai.anthropic_api_key` → `ai.openrouter_api_key`)
- `ai.caption_model` / `ai.refine_model` defaults → `"openai/gpt-oss-20b:free"`
- `requirements.txt`: `anthropic` → `openai`
- Groq fallback chain in `caption_gen.py` unchanged (still free-tier
  Llama 3.3 70B, now falls back from OpenRouter instead of Haiku)
- `classify_groq.py` / `classify_vision.py` untouched — already on Groq

### Fix — country diversity: distinct-country cooldown + "Unknown Location" auto-exclude

Auto-country pick (`diverse` single-clip strategy + merge auto-country pick)
kept repeating the same countries. Root cause: `selection.country_cooldown_posts`
counted the last N **posts**, not N **distinct** countries — a small pool could
post the same country several times inside that window and still count as
"cooldown cleared." "Unknown Location" (IG geodata that failed to resolve) was
also eligible for auto-pick, same as any real country.

- `db.recent_posted_countries(n)` → `db.recent_posted_distinct_countries(min_distinct)`:
  walks recent posts most-recent-first and collects the last `min_distinct`
  DISTINCT countries used, not just the last N posts.
- `selection.country_cooldown_posts` (default 5) → `selection.country_cooldown_countries`
  (default 20) — a country is skipped until that many *other* distinct
  countries have been posted since. Shared by `get_diverse_raw_media()` and
  `get_random_country_for_merge()` (both auto-pickers).
- `"Unknown Location"` is now always excluded from both auto-pickers. It
  remains fully selectable via manual country choice everywhere else
  (Create wizard, `/api/taxonomy/countries`, merge hand-pick).

---

## [v2.0.0 | fe-v2.0.0] — 2026-08-03

### Feature — Reel editor (CapCut-style timeline on top of the merge pipeline)

Accumulating entry; one phase per branch, all landing under the same version.

**Phase 1 — EDL foundation (`feature/editor-core-edl`)**

- `merge_clips.run()` split into `build_plan()` + `render(plan)`; `run()` still
  calls both, so the create/merge/Telegram/daemon paths are untouched. The split
  is what lets an edit round-trip: the plan is the thing the editor edits.
  Guarded by 15 golden fixtures captured at pre-refactor HEAD that assert
  subprocess argv equality and the `upsert_media` payload.
- `editor_edl.py` — EDL v1 (the user document) and PLAN v1 (the compile
  artifact) as pydantic models, `hydrate()` (media row → EDL) and `compile()`
  (EDL → PLAN + EditOverrides). `compile()` is the security boundary: path
  containment for fonts/LUTs/stickers/music, enum whitelists, numeric clamps
  and DoS caps.
- Reels merged from v2.0.0 on persist a trimmed plan at `metadata.merge.plan`
  and round-trip **exactly**. Older reels are reconstructed from the legacy
  `metadata.merge.cuts` spine and are flagged `approx: true` — per-cut slow-mo,
  Ken Burns, cleanup filters, join durations and the music offset were never
  recorded, so re-exporting one produces a close but not identical reel.
- `editor_proxy.py` — content-addressed 480p proxies keyed by
  `sha256(src|in|out|height)`, written to a new `EDITOR_DIR` (a sibling of
  `MERGE_DIR`, so merge cleanup's `rmtree` can never delete them), 2-worker
  encode pool, TTL sweep at 04:00 from the daemon.
- `routes/editor.py` — authed hydrate/save/versions/proxies/export, plus a
  separate public router for the proxy stream: a `<video>` element cannot send
  an Authorization header, so that route carries its own short-lived HMAC
  signature and manual HTTP 206 Range handling. It fails closed when no
  `EDITOR_MEDIA_SECRET` is configured.
- Migration `016_edit_projects` (apply manually, as with 014/015) + `db.py`
  CRUD + settings group `editor`.

**Phase 2 — editor shell + timeline (`feature/editor-shell-timeline`)**

- New route `/editor/:mediaId`, reachable from the Preview page's "Edit
  timeline" button and code-split via `React.lazy` — `@remotion/player` and the
  timeline land in their own 282 kB chunk, leaving the main bundle unchanged.
- `<ReelComposition>` renders the EDL directly: one `<Sequence>` per cut at the
  export's own timing (each cut starts `duration − transition` after the
  previous one), `<OffthreadVideo>` on the signed proxy URL, Ken Burns and
  slow-mo previewed via transform and `playbackRate`.
- Timeline: dnd-kit clip reorder, drag trim handles, split at playhead,
  delete/duplicate, zoom, boundary snapping, scrubbable ruler and playhead, and
  read-only music/text/image lanes whose geometry Phases 3–5 build on.
- Inspector panel for the selected cut (in/out, speed, smooth slow-mo, Ken
  Burns, transition name + duration), every control clamped to the same range
  `editor_edl.py` enforces.
- Debounced autosave (`editor.autosave_seconds`), dirty indicator, in-memory
  undo/redo, unsaved-changes guard, and an export button wired to the WS
  progress events; a viewport under 1024 px gets an "open on desktop" notice.
- Keyboard: space play/pause, J/K/L shuttle, ←/→ frame step, `S` split, `Del`
  remove, ⌘Z / ⇧⌘Z undo-redo, `+`/`−` zoom.
- The `editor` settings group is now editable in the Settings page.

**Phase 3 — text overlays (`feature/editor-text-overlays`)**

- Text layers: content, font, size, colour, x/y, anchor, start/end and fade,
  edited in a new Text tab on the inspector and selectable straight from the
  timeline's text lane.
- Rendered by `editor_layers.py` via drawtext's **`textfile=`**, never `text=`.
  User strings therefore never enter the filtergraph at all — `: ' % \ ,` and
  newlines are structurally harmless rather than escape-dependent. Textfiles are
  written under `EDITOR_DIR/<media_id>/layers/` and read once (`reload=0`).
- Preview parity: the player loads the same TTF from `/static/assets/fonts` via
  `@font-face` at a true 1080×1920 composition, positions layers with the same
  normalized coordinates and anchor rules `editor_layers._position_exprs` uses,
  and fades over the same 0.3 s.
- `video_edit.edit_single()` now accepts `edl_overrides` (the compiled
  `EditOverrides`) and the export route passes it through the orchestrator. For
  an editor export the EDL is authoritative for the LUT — including "no LUT",
  which the pillar/mood auto-pick must not override — and for the branding,
  voiceover, intro and cast toggles. Overlay filters composite last, above the
  grade, the branding bar, subtitles and the screens.
- A failed overlay degrades the reel instead of failing the export.

**Phase 4 — colour + audio (`feature/editor-color-audio`)**

- New **Colour** inspector tab: film-grade profile (with deband/grain/vignette),
  LUT picker, and a brightness/contrast/saturation adjust. Picking a grade
  clears the LUT, because a graded merge makes `video_edit` skip `lut3d` — the
  UI can't offer a look the export won't produce.
- The adjust is rendered by a new `eq=brightness:contrast:saturation` inserted
  **before** the LUT, so the grade still lands on corrected exposure.
- Preview parity is done with a **WebGL shader**, not a CSS filter: CSS
  `brightness()` is multiplicative while FFmpeg `eq=brightness` is additive in
  `[-1,1]`, and CSS has no 3D LUT at all. `ColorVideo.tsx` reproduces
  `vf_eq`'s own maths (contrast/brightness on luma, saturation on chroma about
  the luma axis) and then samples the LUT — the same order as the export.
  Anything that fails (no WebGL, a tainted canvas, a missing texture) falls
  back to the plain proxy rather than breaking the session.
- `backend/scripts/make_lut_previews.py` bakes each `.cube` into the 2D LUT
  strip PNG the shader samples (`assets/luts/_preview/`, served by the existing
  `/static/assets` mount). Run it once after adding LUTs — see below.
  `editor.preview_lut` still turns the LUT preview off entirely.
- New **Audio** inspector tab: bed vs clip audio, track swap, volume, fade,
  entry point (auto = the track's first strong onset, or a fixed offset), and
  the narration duck level. The player now actually plays the bed, at its EDL
  volume and entry point.
- Music **volume** is new all the way through: `MusicSpec.volume` →
  `PlanAudio.volume` → a `volume=` filter on the bed in `merge_clips`. At 1.0 —
  every auto merge — no filter is emitted at all, so the auto-path filtergraph
  is byte-identical to before.
- Merged reels now persist the whole audio decision (mode, fade, volume, track)
  in `metadata.merge.plan`, not just the entry offset, so re-opening a reel in
  the editor no longer silently resets its bed to the defaults.
- Transitions preview by family — wipe, slide, smooth, circle and
  cross-dissolve — instead of every join looking like a fade.

**Phase 5 — image layers, versions, docs (`feature/editor-extras-polish`)**

- New **Image** inspector tab: sticker, logo and watermark overlays. Pick from
  the sticker library or upload a PNG/WebP (10 MB cap), then set position,
  size, opacity, stacking order and timing. `assets/stickers/` ships empty —
  there is no built-in set; uploads and files dropped on the server both show up.
- New `GET /api/assets/stickers` + `POST /api/assets/stickers/upload`, mirroring
  the intros/outros pattern. Each item carries the ASSETS_DIR-relative `asset`
  string an EDL `ImageLayer` stores, so what the picker returns is exactly what
  `compile()` containment-checks.
- Rendered by `editor_layers.build_image_filters()` as one extra ffmpeg input
  and one `overlay` per layer. Images are the *safe* layer type: the asset path
  travels as `-i` argv and never touches the filtergraph, so unlike text there
  is no escaping question at all — only clamped, `%`-formatted numbers are
  interpolated. Position uses overlay's own `x*W-w/2` expressions rather than
  pre-multiplied pixels, which is what keeps the browser's
  `translate(-50%,-50%)` and the render in agreement.
- `_build_cmd` now appends image inputs **after** every audio and voiceover
  input. This is plan risk #6: the music bed is hardcoded as `[1:a]` and
  `voiceover_idx` is positional, so an input inserted anywhere else silently
  corrupts audio on every reel. With stickers the video chain also has to move
  out of `-vf` into `filter_complex` (an `overlay` needs a second input), which
  in turn needs an explicit `-map` when there is no audio graph — ffmpeg's
  default stream selection ignores filter outputs. A separate `[evfx]` label
  keeps the **no-image argv byte-identical** to before; 39 new tests in
  `tests/test_editor_images.py` pin that, including the full
  {none, music, voiceover, both} × {0, 1, 3} images input-order matrix from
  plan §10E.
- Images composite above text, on both sides of the contract.
- **Version history**: a History popover on the top bar lists saved versions and
  loads any one back (`GET /api/editor/{id}/versions/{version}`).
  **Revert to original** (`GET /api/editor/{id}?fresh=1`) rebuilds the edit list
  from how the reel was actually rendered. Neither deletes anything — both land
  as an undoable edit you then save as a new version.
- **Loop friendly** is now editable in the clip inspector: echoes the opening cut
  as the last cut and skips the music fade-out for a seamless loop.
- The timeline's image lane is selectable like the text lane, and an image layer
  with `end_s <= start_s` now draws to the end of the reel instead of collapsing
  to zero width — matching the convention text layers and the renderer already
  used.
- New **Reel editor** section in the Docs page: the EDL/PLAN split, what
  `merge_clips.render()` owns versus what `video_edit` composites, every
  inspector tab, stickers, versions, the `approx` caveat for pre-2.0.0 reels,
  where the preview deliberately differs from the export, the full `editor`
  settings table and the keyboard map.

**Known gaps, deliberately out of scope:** shape layers and an animated progress
bar (a new EDL layer type — a PNG sticker covers the same ground); sticker
uploads are not mirrored into Supabase Storage, because migration 014's `type`
CHECK has no `sticker` value and widening it would also change
`/api/assets/all` and the sync reconcile; and `render()`'s progressive-fallback
ladder strips `zoompan`/`lut3d` on failure but has no sticker tier, since
`compile()` already guarantees the file exists and touching that ladder would
change behaviour for every non-editor reel.

---

## [v1.12.0 | fe-v1.12.0] — 2026-07-25

### Feature — Assets page: search/sort/filter, fixed play timer, richer trim, Audio page merged in

- Assets page gains a shared search/sort/favourites-only/tag-pillar-chip
  toolbar above the library grid, applied to whichever of the 5 tabs
  (Music/Fonts/LUTs/Intros/Outros) is active — search matches name/title +
  filename + tags/pillars; sort covers favourite-first, recently-used,
  most-used, name (A-Z), and date-added. All narrowing is client-side over
  the already-fetched list — no new query params, no extra requests while
  typing or toggling filters.
- Fixed the music track play button: it never actually tracked playback
  position (no live counter, no progress bar — not a regression, just always
  missing). Now shows a live `mm:ss / mm:ss` counter and progress bar while
  playing, ported from `MusicPicker.tsx`'s existing working pattern.
- WaveformTrimModal enhancements: numeric start/end second inputs with
  ±0.1s nudge buttons (in addition to drag), a "Loop selection" toggle that
  previews just the trimmed region on repeat, a waveform zoom slider, and
  fade-in/fade-out (0–5s) applied server-side on save. `trim_track()` now
  re-encodes (instead of the fast stream-copy path) only when a fade is
  requested — zero-fade trims are unchanged.
- The standalone Audio page is retired: its Library/Refresh/dedup features
  and `TrackCard`/`PillarEditor` (moved to `components/audio/TrackCard.tsx`)
  are folded into the Assets page's Music tab, which now shows both **Sync**
  (Storage/DB reconcile, all tabs) and **Refresh** (local dedup + orphan
  prune, Music tab only — a different operation, both still needed). The old
  `/audio` route redirects to `/assets?type=music`; the sidebar's separate
  "Audio" entry is removed.
- No new settings keys, no new migrations.

---

## [v1.11.0 | fe-v1.11.0] — 2026-07-24

### Feature — Assets metadata cutover: favourite/usage/tags on every type

- Migration `015_assets_metadata_columns.sql` promotes `favourite`, `usage_count`,
  `last_used_at`, `tags`, `pillars`, and `mood` from music-only `meta` JSONB to
  real columns on the `assets` table, covering all five types (music/font/lut/
  intro/outro). One-time backfill promotes existing music `meta.*` values into
  the new columns on apply.
- `assets` table is now the source of truth for these fields — `music_fetcher.py`
  reads them through a shared overlay helper (`_overlay_asset_fields`) so
  selection scoring, `list_all_tracks()`, and the Audio page all see the same
  values, while `cache.json` keeps only physical bookkeeping (filename/source/
  duration/license) plus a stale-but-present fallback when Supabase is
  unreachable — reel creation never blocks on a live Supabase read.
- Net-new usage tracking for LUTs, fonts, and intro/cast screens: `usage_count`
  auto-increments the first time each is actually applied to a rendered reel
  (`lut_select.py`, `video_edit.py`, `screens.py`) — best-effort, never fails a
  render.
- `GET /api/assets/all` gains `favourite`/`pillar`/`tag` query filters; `PUT
  /api/assets/all/{id}` accepts `favourite`/`tags`/`pillars` patches.
- Design page: LUT and font pickers (`LutPicker.tsx`, new `FontPicker.tsx`) now
  read from `/api/assets/all` instead of the old local-scan endpoints, with an
  inline favourite-star toggle and tag/pillar filter chips.
- Preview page: post detail panel shows the resolved music track's name
  (linking to the Assets page) with an inline favourite toggle and usage-count
  badge (`AssetResolvedChip.tsx`). LUT resolution is not shown yet — no LUT
  filename is persisted on the media row today, a separate gap outside this
  cutover's scope.
- **Manual step required**: apply `015_assets_metadata_columns.sql` to Supabase
  (same as `014_assets_table.sql`) — every code path degrades gracefully
  (falls back to `cache.json` / returns defaults) until it's applied.

---

## [v1.10.0 | fe-v1.10.0] — 2026-07-22

### Feature — Assets indexed into Supabase (Storage + `assets` table)

- New `assets` Postgres table (`supabase/migrations/014_assets_table.sql`) indexes
  music, fonts, LUTs, intros, and outros with a `type` discriminator + `meta jsonb`
  for type-specific fields. Backed by a **public-read** Supabase Storage bucket
  (`SUPABASE_STORAGE_BUCKET`, `backend/config.py`) so every asset gets a stable
  permanent `public_url` — no signed URLs, no auth needed to fetch a file.
- Local disk stays the fast-serve path and the FFmpeg pipeline's only source of
  truth (`merge_clips.py`/`video_edit.py`/`screens.py`/`lut_select.py` untouched,
  still read local paths directly) — the DB row is authoritative for the admin
  surface only. Read order: local file if present, else `public_url`.
- `backend/pipeline/assets_index.py` — `reconcile(type, dry_run)` walks local
  disk + the Storage bucket + existing DB rows and upserts/prunes accordingly,
  mirroring `music_fetcher.discover_new_files()`'s orphan-prune shape. **Never**
  deletes a local file, and never prunes a row missing from only one side (local
  *or* Storage) — only when missing from both. If a bucket listing comes back
  empty while the DB already holds Storage-backed rows for that type, bucket
  state is treated as unknown (not confirmed-empty) — no pruning fires off a
  transient Storage read failure.
- `backend/pipeline/storage_supabase.py` — thin wrapper over the existing
  Supabase client's `.storage.from_(bucket)` API (list/upload/delete/public_url),
  never raises on a misconfigured/unreachable bucket — degrades to empty/no-op
  everywhere so environments without Supabase Storage creds are unaffected.
- New CRUD routes on `backend/api/routes/assets.py`: `GET /api/assets/all?type=`,
  `GET/PUT/DELETE /api/assets/all/{id}`, `POST /api/assets/sync?type=&confirm=`
  (two-step preview/confirm, same UX as `/api/audio/refresh`). All 5 pre-existing
  routes (`/music`, `/luts`, `/fonts`, `/intros`, `/outros`) are unchanged —
  `MusicPicker`/`LutPicker` need no updates.
- Music trim/create-new-track (`music_fetcher.trim_track()`) now also uploads
  the trimmed file to Storage and inserts a linked `assets` row
  (`parent_asset_id` → source track) when Storage is configured, so trims are
  immediately playable via a public URL, not just a local path.
- New **Assets** admin page (`frontend/src/pages/Assets.tsx`, nav entry in
  `AppLayout.tsx`) — tabs for Music/Fonts/LUTs/Intros/Outros, reuses `Audio.tsx`'s
  `TrackCard`/`PillarEditor`/`WaveformTrimModal` for the Music tab, a simple
  card grid (rename/delete/preview) for the other four, upload panel per type,
  and the same two-step sync preview/confirm banner pattern as the Audio page.
- `IntroSection.tsx`'s previously-disabled intro-asset upload button now links
  into the Assets page (`/assets?type=intro`) instead of doing nothing.
- **Manual steps required before this is live** (not done by this change):
  create the Supabase Storage bucket + public-read policy in the dashboard,
  apply `014_assets_table.sql` to prod, and upload the existing `assets/` files
  into the bucket.

---

## [v1.9.0 | fe-v1.9.0] — 2026-07-22

### Fix — Music selection no longer silently falls back to blind random picks

- `music_fetcher.py` cached tracks by **pillar-bucket** and resolved every
  candidate's file path as the hardcoded `packs/<pillar>/<filename>`. Any track
  whose physical file didn't live in exactly that folder (moved, consolidated,
  or living in a folder that isn't a pillar name at all — e.g. the hand-curated
  `packs/travel/` pool of IG-downloaded tracks) silently failed the on-disk
  check for every scored candidate, and the picker fell through to Jamendo API
  search and then to a **plain `random.choice()` with zero scoring** — throwing
  away all mood/duration/source-quality weighting. `packs/travel/`'s 12 tracks
  were never selectable under the old scheme.
- `cache.json` migrated to a flat, id-keyed schema (`{"tracks": {id: {...,
  "pillars": [...], "favourite": false, "usage_count": 0}}, "_recent_picks":
  [...]}`) with a transparent one-time migration on first load (no manual step
  — verified lossless against the live cache: 361 legacy bucket entries → 181
  unique tracks, pillars correctly unioned for tracks referenced by multiple
  buckets). Path resolution now walks `assets/music/` directly (rglob, cached
  in-process) instead of assuming a fixed folder layout, so every pool —
  including `travel/` — is reachable regardless of physical location.
- Merged reels never received caption-derived mood matching (`music.mood_match`
  only wired into the single-clip edit path) — merge's audio-bed pick now
  derives mood the same way and passes it through, so merged reels get
  mood-matched beds too.

### Feature — Audio Management page + favourite/usage-weighted scoring

- New **Audio** admin page (`/audio`): browse every track, play/pause preview,
  favourite (★), edit pillar tags, trim with a waveform editor (region-select →
  save as new track), delete, upload, and a **Refresh** button that scans
  `assets/music/` for newly-added files (e.g. freshly downloaded IG audio
  copied onto the server) and registers them — no code change needed to pick
  up new tracks. Refresh runs a safe two-step dry-run-then-confirm flow before
  deleting any duplicate physical files it finds.
- Selection scoring now factors in **favourite** (fixed bonus) and **usage
  count** (log-scaled bonus, so proven tracks are favored without dominating)
  alongside the existing source/mood/duration/popularity/cooldown signals.
- New backend router `/api/audio` (list/upload/edit/delete/trim/refresh).
  `/api/assets/music` (used by the existing in-flow `MusicPicker`) keeps its
  response shape unchanged, now backed by the same underlying track catalogue.
- New settings: `music.favourite_boost` (3.0), `music.usage_weight` (0.3),
  `music.cooldown_recent_cap` (10, replaces a hardcoded constant).

### Fix — Stale cache entries, missing static mount broke Play/Trim

- `discover_new_files()` registered new files and deduped physical copies but
  never removed cache entries whose file had since been deleted from disk —
  after manual library pruning, 161 of 181 cached tracks pointed at nothing,
  which is what the Audio page was showing. Added an orphan-prune pass (same
  dry-run-preview → confirm flow as the dedupe pass) that drops dead entries;
  running it against the live cache brought the library down to 32 real,
  resolvable tracks and picked up the 12 new `travel/` files in the same pass.
- `/static/assets` (music/LUTs/fonts/intro-outro — none of which ever get
  uploaded to R2) was mounted only when `SERVE_LOCAL_MEDIA=true`, the same gate
  used for the R2-backed organized-media mount. Locally that env var wasn't
  set, so every audio fetch 404'd — Play and the waveform Trim editor both
  depend on this route and had nothing wrong with their own logic. The assets
  mount is now unconditional (no R2 fallback exists for it, so it should never
  have been opt-in); the organized-media mount keeps its existing opt-in gate.

### Feature — Choose Single vs Merge for Auto Create

- New setting `pipeline.auto_create_reel_type` (`"merge"` | `"single"`, default
  `"merge"`) controls which pipeline the daemon runs at each scheduled slot when
  `pipeline.auto_create_enabled` is on. Previously the auto-create daemon always
  built a single-clip reel and ignored the merge feature entirely, even with
  `merge.enabled`/`merge.auto_run` on — those flags only affected the manual
  Create page.
- `merge` mode randomly picks a country from the available raw-VIDEO pool
  (weighted by clip count, quality-gated, cooldown-aware — same mechanism as
  the existing `diverse` strategy) when `pipeline.auto_create_country` is
  empty, so consecutive auto-create ticks don't keep repeating one country.
  Falls back to single-clip creation for that tick if no country has any
  footage.
- Saving `auto_create_reel_type=merge` in Settings also flips `merge.enabled`
  on automatically, so the daemon doesn't silently no-op with the feature gate
  off.
- `mode=publish` (auto-publish at slot time, no approval gate) now also works
  for merge reels — `_merge_and_enqueue` forwards `auto_publish_slot` through
  to the enqueue step, which it previously dropped.

---

## v1.8.2 — 2026-07-08

### Fix — Merge reels always reach the target duration (no more 9s stubs)

- A thin or short-clip country pool could ship a merged reel far under
  `merge.target_duration_s` (observed 9s). The `min_segments` floor only bounds
  the cut **count**; with every cut clamped to `cut_max`, a handful of short cuts
  still fell short, and the adaptive-duration rescale only ran when cv2 was
  present. A final **minimum-duration guarantee** now runs before render: it
  stretches each hold to spread the timeline across the cuts actually available
  (each still bounded by its own clip length), and — when the footage is
  physically too short — loops the montage until it fills the target. Reels that
  already reach the target keep their beat-synced/adaptive cut lengths untouched.

- Merge no longer OOM-crashes (`xfade killed by signal 9` / `xfade render failed`)
  on small-RAM hosts. The per-segment motion FX (Ken Burns `zoompan` + slow-mo) used
  to run **inline in the single delivery filtergraph**, so 15-20 `zoompan` instances
  decoded at once and peak RAM scaled with the cut count — the OS OOM-killer took
  ffmpeg down (SIGKILL). Those FX are now **baked into each segment file up-front**,
  leaving the delivery pass as a lightweight **xfade-only** chain; peak RAM is bounded
  to one `zoompan` at a time. FX is duration-preserving, so cut lengths and xfade
  offsets are unchanged (a segment whose bake fails keeps its FX inline).

- Merge OOM follow-up: FX pre-baking alone was **insufficient** — the delivery pass
  still opened **all N segment inputs in one ffmpeg process**, so 15-20 concurrent
  1080p H.264 decoders + a deep `xfade` chain kept peak RAM at O(cut count) and the
  OOM-killer still fired. Reels beyond `_XFADE_MAX_INLINE` (6) cuts now **fold two
  segments at a time to disk** (`_incremental_xfade`): each ffmpeg opens only the
  running accumulator + the next segment (2 inputs), so peak RAM is bounded no matter
  how many cuts. The single folded file then feeds one delivery pass (grade + music).
  Per-join transition variety / hard-cut-on-beat overlaps are preserved; fold totals
  and offsets match the monolithic chain exactly. Small reels keep the cheaper
  single-pass graph; a fold failure falls back to the monolithic path.

- Fixed `create` 500 (`UnboundLocalError: asyncio`) when merge `auto_run` was on:
  a redundant function-local `import asyncio` shadowed the module import.

- Decaption (ONNX) no longer emits a `CUDAExecutionProvider` warning on CPU-only
  hosts — providers are intersected with what onnxruntime actually offers.

### Enhancement — Stock footage: HD-not-4K downloads + per-clip delete

- **HD, not 4K** — imports now pull the ~720p rendition instead of the largest
  available file, cutting storage without hurting 9:16 reel quality. Pexels takes
  the largest file ≤720p (falling back to the smallest available so it never grabs
  4K); Pixabay takes the 720p `medium` tier.
- **Delete a stock clip** — each clip in the Stock-library view has a trash button
  that hard-deletes the file from disk *and* the media row to reclaim storage.
  New route `DELETE /api/downloads/stock/{media_id}` (source="stock" rows only).

### Enhancement — Merge reels: stock/local segment quota

- Merged montages now guarantee a floor of **stock B-roll AND local-archive**
  clips per reel — default **8 stock + 12 local = ≥20 cuts**. A thin pool on one
  side tops up from the other so the reel always fills to target length.
- `merge.min_segments` floor raised **15 → 20** (clamp now 15–30).
- New settings `merge.split_stock_local` / `merge.min_stock_segments` /
  `merge.min_local_segments`; the last two are per-run overridable in the Create
  merge wizard's new **Segment mix** panel.

### Enhancement — Merge reels: auto-source stock when a country has none

- Opt-in `merge.auto_fetch_stock`: when a merge's country/pillar has **no stock
  clips yet**, the run downloads a few clips per provider (default **3 Pexels +
  3 Pixabay**, pillar→country query) *before* selection, so they're pickable in
  the same reel. Requires `stock.enabled` + a provider key; best-effort — a
  provider with no key or a failing call is skipped, never aborting the merge.
- Counts tunable via `merge.auto_fetch_pexels` / `merge.auto_fetch_pixabay`.

---

## v1.8.1 — 2026-07-07

### Enhancement — Stock tab: imported-clip library, per-country breakdown, dedup

The Download page's Stock tab now shows what you've already imported, not just a
search box:

- **Imported library** — a summary above the search grid: total clips + total
  on-disk size, then a collapsible per-country breakdown down to each clip
  (provider, dimensions, duration, file size, city/pillar, import order).
- **By Country tab** — a compact "Stock footage" strip under the archive tree
  shows imported stock per country (clip count + size), so stock is visible
  alongside archive footage.
- **Duplicate prevention** — search results already in your library are badged
  "In library" with the Import button disabled, and the server rejects a repeat
  import of the same provider clip (`{"duplicate": true}`) even if two tabs race.
  Dedup keys are parsed from the stored `<provider>_<id>_<uuid>` filename — no
  new DB column or migration.

New backend route: `GET /api/downloads/stock/library` → per-country imported
clips + `imported_keys` for the search grid.

### Fix — merged reels landing short of the 30s target

When `merge.adaptive_fx` was on (default) and OpenCV was available, the
quality-driven per-cut durations were rescaled to sum to exactly
`target_duration_s`, ignoring the crossfade overlap the xfade chain later
subtracts. The rendered reel therefore came out `~(n-1)×transition_ms` short —
about 7s under at 15 cuts, matching the observed 20-29s reels. The adaptive path
now compensates the target for crossfade overlap + per-cut frame headroom, the
same way the non-adaptive `base_seg` path already did, so montages land on
target (≥30s).

### Fix — imported stock/upload clips excluded from merge selection

`insert_upload_row` (manual uploads + stock imports) set `pillar` and `country`
but no `hook_score`, so `_is_classified` treated the rows as unclassified and
`selection.require_classified` (default on) excluded them from merge/single picks
whenever the same country had any classified archive clip — the reason imported
stock B-roll never appeared in merged reels. Stock/upload rows now get a neutral
baseline `hook_score` (0.5) on insert (overwritten by any later real classify
pass), making them eligible immediately.

**Note:** `merge.loop_friendly` intentionally echoes the opening cut as the final
cut (seamless TikTok/IG loop) — that is the source of an identical first/last
clip. Turn the setting off in Settings if you don't want the looped bookend.

### Fix — Pexels stock import always failed (wrong get-video-by-id URL)

`PEXELS_SHOW_URL` was `https://api.pexels.com/v1/videos/{id}`, which 404s. The
correct Pexels endpoint is `https://api.pexels.com/v1/videos/videos/{id}`
(doubled `videos`). `_pexels_lookup` therefore always failed and
`import_stock_clip` raised "could not resolve pexels video id" for every Pexels
clip picked from the Stock tab. Corrected the URL (verified live against the
API). Search + Pixabay paths were unaffected.

### Required Supabase migration — allow `source='stock'`

Stock imports write media rows with `source="stock"`, but the pre-existing
`media_source_check` CHECK constraint predates the feature and rejects the value
(`violates check constraint "media_source_check"`, code 23514). Rebuild the
constraint once to include `stock`:

```sql
-- confirm current values first, add any extras this surfaces to the list below
SELECT DISTINCT source FROM media;

ALTER TABLE media DROP CONSTRAINT media_source_check;
ALTER TABLE media ADD CONSTRAINT media_source_check
  CHECK (source IN ('post','story','highlight','upload','stock','merge'));
```

---

## v1.8.0 — 2026-07-06

### Feature — Stock footage sourcing (Pexels/Pixabay)

Search Pexels/Pixabay for stock B-roll matching a country/pillar keyword and index
results as raw media alongside your own archive footage. Once indexed, the existing
merge montage builder (`merge_clips.py`) already blends stock clips WITH archive
footage in the same country reel — zero merge-side changes needed.

- **New Download page "Stock" tab** — search → thumbnail grid → per-clip import,
  mirroring the existing Google Drive import flow.
- New settings group `stock.*`: `enabled` (opt-in, default off), `source`
  (`pexels` | `pixabay` | `both`), `per_pillar_query`, `max_clips_per_search`,
  `min_short_side`, `min_duration_s`.
- Requires a free `PEXELS_API_KEY` and/or `PIXABAY_API_KEY` in `.env`.

### Feature — TTS voiceover + burned subtitles

Generate a spoken narration of a reel's caption hook line via `edge-tts` (free,
MIT), mux it as the primary audio track (ducking the music bed underneath), and
burn word-synced subtitles from the same synthesis pass — no separate
transcription step needed, since narration text is known before speech is
generated (a key simplification vs. running a full transcription model).

- New `voiceover` pipeline stage, self-gated like `decaption`, running after
  `caption` and before `edit`; results (`voiceover_path`, `voiceover_srt_path`)
  are cached on the media row and reused.
- New settings group `voiceover.*`: `enabled` (opt-in, default off), `voice`,
  `rate`, `narration_source`, `subtitles_enabled`, `subtitle_position`,
  `subtitle_font_size`, `subtitle_color`, `music_duck_volume`.
- **Requires a manual Supabase migration before enabling:**
  ```sql
  ALTER TABLE media ADD COLUMN voiceover_path TEXT;
  ALTER TABLE media ADD COLUMN voiceover_srt_path TEXT;
  ```
- Per-post override: `voiceover: true|false|null` on `/api/posts/create` and
  `/api/posts/create-merge` (mirrors the existing `decaption` override field).

---

## v1.7.1 — 2026-07-05

**Fixes (post-freshness):**
- **Short reel** — diversity + anti-repeat could starve a montage (small country
  pool, or a repeat same-country reel whose fresh windows were all excluded with no
  proven pool to top up), shipping a ~9s stub. A **fill guard** now backfills the
  montage to the target cut count from the resolved sources (reusing distinct
  windows only as a last resort) so the reel always reaches its target length. The
  `min_fill` diversity check also now accounts for crossfade overlap, so medium
  pools no longer land ~5s under target.
- **Original audio on merge** — the Create wizard forced each clip's raw audio when
  no music track was picked; it now falls back to the **auto mood-matched music
  bed** (the merge default). Single-clip flow still keeps the clip's original audio.

---

## v1.7.0 — 2026-07-05

### Feature — Merged-reel quality enhancement (CPU-only)

The multi-clip merge montage (`merge_clips.py`) gains a cinematic quality pass so
merged reels look high-quality and trend-native — all **CPU-only**, using FFmpeg +
OpenCV (both already installed). No GPU, no new dependency, no new pipeline stage.
Every improvement is a `merge.*` toggle; the two CPU-heavy ones default **off**.

**Research note.** The four referenced repos (leclap, videoalchemy, ffmpeg-ai,
REAL-Video-Enhancer) were evaluated and **not** integrated — three are FFmpeg
wrappers / topic-generators with nothing we lack, and REAL-Video-Enhancer needs a
GPU (AGPL-licensed). The highest-leverage CPU gains were in refining our own
filtergraph plus one lightweight OpenCV scoring pass. Full report in
`plan/merge-clips-reel-enhancement.md`.

- **Per-clip adaptive treatment** (`merge.adaptive_fx`, default on) — the headline
  change: instead of applying the same effect to every clip by index, each clip is
  treated by its *own* content (from the OpenCV metrics). Stronger clips (sharper,
  better-exposed, higher hook) hold **longer** on screen; weaker clips flash by.
  **Calm/scenic** clips get slow-motion + a Ken Burns push (dreamy hold); **action**
  clips stay real-time. **Soft** clips get sharpened (strength scaled by softness);
  only **dark/noisy** clips get a light denoise. Turn it off to fall back to the
  fixed alternating rules. Degrades gracefully to those rules when OpenCV is absent.
- **Smart cut selection** (`merge.smart_select`, default on) — picks the *best*
  sub-shot of each clip via cheap OpenCV scoring (sharpness = variance of
  Laplacian, exposure sanity, motion sanity) with a colour-histogram variety guard,
  instead of just the longest scene. Falls back to longest-scene when OpenCV is
  unavailable. Tunables: `merge.select_sharpness_weight`, `merge.select_min_sharpness`.
- **Colour consistency** (`merge.color_match`, default on) — gentle per-segment
  gray-world white-balance nudge (±12% max) so mixed-source clips don't jump in
  colour cut-to-cut. Plus `merge.deband` (default on) to kill sky/gradient banding
  the grade introduces. Three new `merge.grade` film profiles: `teal_orange`,
  `golden_hour`, `vivid_pop`.
- **Motion & transitions** — eased (smoothstep) Ken Burns with occasional
  off-centre drift; `merge.hard_cuts_on_beat` (default on) mixes ~1-frame hard cuts
  among the crossfades for a punchier rhythm; expanded transition-variety set;
  `merge.smooth_slowmo` (default **off**, CPU-heavy) for judder-free
  motion-compensated slow-mo, capped by `merge.smooth_slowmo_max_s`.
- **Detail / de-artifact** — `merge.deblock` (default on) removes IG-compression
  blocking per segment; `merge.sharpen` (default off, avoids double-sharpen with
  `video.sharpen`); `merge.strong_denoise` (default **off**, CPU-heavy nlmeans).
  No neural upscaling — that needs a GPU; detail work is an FFmpeg sharpness
  *illusion*, not true super-resolution.

### Feature — Freshness & Variety (non-repeating same-country reels)

A second (third, Nth) merged reel from the **same country** now looks different from
the last, so viewers don't see duplicated montages. Each reel records the sub-shots
it used — source clip + timestamp + aesthetic score — in **its own metadata** (the
`mrg_` row's `cuts`). No new table, **no migration**, no cached clip files, no disk
budget: reuse simply re-cuts a clip on demand from the stored timestamp.

- **Anti-repeat** (`merge.dedupe_enabled`, default on) — a new reel reads the recent
  same-country reels' memory and **hard-excludes** sub-shots used within the last
  `merge.subshot_cooldown_reels` (default 3) reels; past the cooldown a shot is kept
  but **down-weighted** (`merge.dedupe_soft_weight`, default 0.5). The first reel of a
  country has no history and behaves exactly as before.
- **Diversity-first counts** (`merge.dynamic_count`, default on) — the cut count now
  scales to how much footage the country actually has, and the montage spreads across
  **as many different clips as possible** (one cut per clip while distinct clips
  remain, via `merge.max_cuts_per_source`, default 1). Small pools relax the cap
  automatically so the reel still fills its target length; the old fixed
  `min_segments`/`clips_per_reel` path is used when the toggle is off.
- **Proven top-up** (`merge.proven_topup`, default on) — when the fresh pool can't
  fill the reel, it tops up with the **highest-scoring** previously-used sub-shots
  (score ≥ `merge.proven_min_score`, default 0.5) instead of falling short — "mostly
  fresh, a few proven".

Degrades gracefully: no OpenCV / no history / dedupe off ⇒ the fresh-only,
longest-scene behaviour. New keys documented in **Docs → Video enhancement**.

**Backwards-compatible:** with every new toggle set to its "old behaviour" value,
the rendered reel matches pre-1.7.0 output. Heavy filters are opt-in so the default
render path stays fast. New keys documented in **Docs → Video enhancement** and the
Settings reference.

---

## v1.6.0 — 2026-07-04

### Feature — Create wizard Customize step (music + LUT + clip preview)

The Create Video flow gains a **Customize** step between filters and confirm, for
both Single and Merge modes, so music and colour grade can be chosen per reel at
creation time — and a single-clip pick can be reviewed before any processing runs.

- **Clip preview + re-pick (single mode).** After picking filters, the wizard
  dry-run selects a clip via the new `POST /api/posts/select-preview` endpoint
  (pick only, no pipeline) and shows its `media_id`, source path, location and
  duration. **Pick new video** re-selects a different clip, excluding ones already
  skipped, so you can cycle candidates before committing.
- **Music + LUT picks (both modes).** Reuses the `MusicPicker` and `LutPicker`
  components, each now with a **search box** to filter tracks / LUTs. Single:
  `music_path` + `lut` on `POST /api/posts/create` are applied at the edit stage.
  Merge: passed as `overrides.music_path` (muxed at the merge stage) +
  `overrides.lut` (rides the edit tail).
- **Keep original when blank (manual flow only).** If no track is picked, the
  clip's own audio is kept (no auto-added music bed); if no LUT is picked, no
  colour grade is applied (original video look). For merge, blank music uses the
  clips' own audio (`audio_mode=original`). Wired via new `keep_original_audio` +
  `no_lut` flags threaded through the orchestrator to the edit stage. **The
  automatic timer/daemon flow is unchanged** — it still auto-picks music and
  auto-grades (the new flags default off).
- **Per-reel decaption toggle.** The Customize step has a decaption on/off switch
  that seeds from the global `decaption.enabled` setting and can force it either
  way for just this reel (`decaption` field on both create endpoints →
  `decaption_force` through the orchestrator / merge stage). Auto flow keeps
  respecting the global setting.
- **Flow buttons.** Customize offers **Continue** → Confirm, **Pick new video**
  (single), **Back** → filters, and **Cancel** → restart the flow. Confirm now
  restates the picked clip, music and LUT.
- **New endpoint** `POST /api/posts/select-preview` (dry-run clip select). `POST
  /api/posts/create` accepts new optional `media_id`, `music_path`, `lut` fields;
  `POST /api/posts/create-merge` accepts `overrides.lut`.

No new settings keys — music/LUT are per-request picks, not persisted config.

---

## v1.5.0 — 2026-07-03

### Feature — Decaption (strip burned-in captions/watermarks)

New opt-in `decaption` pipeline stage that removes burned-in Instagram
captions/watermarks from source clips so both single-clip create and merged
reels use clean, original-looking footage — a lift for IG originality/reach.

- **Vendored `video-text-remover` (hjunior29, MIT).** YOLO11 text detection +
  OpenCV inpaint (hybrid / TELEA / Navier-Stokes) on ONNX Runtime — CPU-friendly,
  no GPU required. Audio is re-muxed after inpaint (the library drops audio).
- **Clean once, reuse everywhere.** Each source clip is decaptioned a single time
  and the result is cached on the media row (`decaptioned` + `decaptioned_path`),
  then reused across every future reel. Wired into single-clip create (runs
  **before** resize) and merge (per-source cached pre-pass).
- **New settings group `decaption` (7 keys, default OFF):** `decaption.enabled`
  (master gate), `decaption.algorithm` (`hybrid` | `telea` | `ns`),
  `decaption.detect_mode` (`auto` | `bottom` | `top` | `custom`),
  `decaption.custom_bbox` (`"x,y,w,h"` when `detect_mode=custom`),
  `decaption.min_confidence` (YOLO11 threshold, default `0.35`),
  `decaption.dilate_px` (mask expansion, default `6`), and `decaption.fallback`
  (`blur` | `fill` | `none` on inpaint failure).
- **New media columns:** `decaptioned` (INT flag) + `decaptioned_path` (TEXT).
- **One-time manual setup required before enabling.** Run
  `backend/scripts/setup_decaption.py` (pip-installs onnxruntime/opencv + fetches
  the YOLO11s weights) and apply the Supabase migration:
  `ALTER TABLE media ADD COLUMN decaptioned INT DEFAULT 0; ALTER TABLE media ADD COLUMN decaptioned_path TEXT;`

---

## v1.4.0 — 2026-07-02

### Fixes — publishing, rendering, captions, merge music

- **Duplicate-publish guard (never post the same clip twice).** `publish_post` now
  skips any platform that already carries its published id (`ig_media_id` /
  `yt_video_id` / `tiktok_video_id` / Zernio ids) and returns the existing id
  instead of re-uploading. Covers auto-publish, approve, and manual re-publish.
- **YouTube auto-publish reliability (#1).** Before a YouTube upload the publisher
  now ensures a public `r2_url` exists (uploads from `reel_ready_path` if missing,
  mirroring the retry-youtube path), so an auto-publish tick after local cleanup no
  longer fails silently. YouTube/TikTok failures now surface as an in-app
  notification **and** a Telegram message instead of being swallowed; a successful
  retry clears `yt_error`.
- **Render now reflects new music / LUT (#3).** The Preview edit drawer's music
  swap is threaded end-to-end (`edit.py → orchestrator → video_edit`) — previously
  the picked track was dropped and the old bed re-played. Every edit dispatch now
  also re-runs the **upload** stage so the fresh reel reaches R2 and the player
  loads the new video (with cache-bust) instead of the stale one. Music swap also
  works on merged reels (the baked bed is replaced).
- **Merged-reel music enter-point + source priority (#4).** The montage music bed
  now enters at the track's first strong onset (the "drop") via librosa instead of
  the quiet intro. Local-pack source ranking split to **Pixabay (pxb_audio) >
  Chosic > Jamendo** trending.
- **Caption regenerate updates all platforms (#5).** Regenerating a caption in
  Preview now also refreshes `caption_ig`, `caption_tt`, `caption_yt_title`, and
  `caption_yt_description` (derived locally from the new caption) on both the media
  row and the post — previously only `caption` changed, so IG/TikTok/YouTube
  published stale text.
- **Preview publish button (#2).** Each platform row shows a badge with the
  returned publish id once published, and the Publish button stays clickable
  (re-publish is safe — the backend blocks the duplicate and returns the existing
  id).

---

## v1.3.0 — 2026-06-30

### Phase 1 — Skill-Driven Enhancements

#### Part A — Strategy (A1): Send-prompt CTA
- `caption.cta_style` (send|save|follow, default send): controls the last-line CTA in every generated caption. `send` produces a named-persona send prompt ("Send this to the friend who keeps saying let's go to {country}") — the highest cold-reach signal per the Mosseri sends-per-reach hierarchy. `save` and `follow` reproduce the prior behavior.
- `cast.cta_text` default changed from "Follow for more" to "Send this to your travel buddy 🌍".
- Settings page: new dropdown for `caption.cta_style` under the Caption group.

#### Part B — Format (B1/B2): Duration clamp + intro opacity
- `merge.target_duration_s` clamp widened from 20–45s to **20–60s**: TikTok's 15-30s and YouTube Shorts' ~55s sweet spots are now reachable by setting `target_duration_s` in the Merge settings. Default (30s) unchanged.
- `intro.bg_opacity` and `cast.bg_opacity` defaults reduced 0.20→**0.15**: lighter tint preserves the visual hook in the first 1.5s.
- `schedule.daily_slots` default confirmed covering IG peak 11-18 window (no code change needed).

#### Part A Phase 2 — Hook ordering + minimal cast
- **A2** `intro.show_hook` (bool, default false): when enabled, burns the caption's first line as a bold hook headline on the intro overlay (`hook_font_size` 56). Source: `intro.hook_source` = `caption_line1` (auto-parsed from stored `media.caption`) or `manual` (`intro.hook_text`). Converts the branding card into a first-frame retention + SEO lever.
- **A5** Caption line 1 now leads with the destination keyword phrase in the first 5-7 words — IG caption SEO aligns with `caption_yt_title` discipline.
- **A6** `cast.minimal_cta` (bool, default false): when true, the cast screen shows only the CTA text, suppressing country/city/episode/handle stacking — clean closing beat for a send-prompt CTA.

#### Part C — FFmpeg Engineering (C1/C3/C8): Correctness + CPU win
- **C1** `-pix_fmt yuv420p` added to every delivery encode (resize, edit, merge, enhance, screens). Prevents IG/QuickTime/Safari rendering black or green on 10-bit / yuv422 / yuv444 source footage (phones, drones, screen captures). Silent-breakage fix — no visible quality change.
- **C3** Merge segment intermediates now encode at `ultrafast/crf18` instead of the delivery `preset/crf`. Segments are transient xfade inputs — ultrafast is visually lossless at this stage and ~5-10× faster, cutting merge CPU time significantly on the Hetzner CX33. Redundant second `_NORM_FILTER` pass inside `_fx_segment` removed (segments already normalized by `_normalize_segment`).
- **C8** `resize_clips` now appends `,setsar=1,fps=30` to the crop/scale filter — single-clip reels are now locked to square SAR and 30fps, matching merge segments and burn_screens output.

### Phase 2 — Algorithm & Sequence Improvements

- **A4/B5** Merge montage opener pinning: after shuffling source clips, the clip with the highest `hook_score` (fallback: `quality_score`, then random) is moved to position 0 — the opening cut always leads with the strongest visual. Hand-picked merges (explicit `media_ids`) are unaffected (user order preserved).

### Phase 3 — Part A (A9): Hashtag enforcement

- Hard 5-tag cap in `_apply_hashtag_policy` (caption_gen.py) — LLM-generated sets can't exceed 5 tags even on re-runs
- Fix `hashtag_engine.blend_count` hardcoded fallback 8 → 3, matching the documented settings default

### Phase 3 — Part B (B4): Loop-friendly merge format

- New `merge.loop_friendly` (default false): echoes the opening sub-shot as the final cut and strips the music fade-out so TikTok loops back to the start without a visual/audio gap
- Cast screen suppressed on loop-friendly merges (stored in merge metadata, checked by video_edit)

### Phase 3 — Part C: FFmpeg engineering

- C2: Generated intro/cast screens fold into the VideoEditor encode pass — eliminates one ffmpeg subprocess per reel when screens are enabled
- C5: vidstab pass-2 + quality chain combined into one encode; eliminates `_stabilized.mp4` intermediate file
- C6: `best_audio_offset()` replaced with single ebur128 pass (was up to 10 volumedetect spawns)
- C7: `_RENDER_SEM = threading.Semaphore(2)` added to resize_clips, enhance_video, video_edit, screens — bounds concurrent encode load

### Telegram Bot Enhancement

- Per-platform publish buttons on preview: one button per enabled platform (📸 IG / 🎵 TikTok / ▶️ YT) plus Approve All
- New admin controls: ✏️ Edit caption (AI refine or verbatim replace), ℹ️ Details, 🕐 Reschedule menu (+1h/+3h/+1d), 🔄 Regenerate
- Rich preview always pushed at creation, including auto-publish mode (`telegram.always_preview`, default true)
- Post-publish daemon notification now loads media details, caption excerpt, and Watch link (`telegram.rich_publish_notify`, default true)
- Admin buttons can be hidden for minimal approve/reject-only UI (`telegram.admin_controls`, default true)
- Fix: TikTok auto-publish no longer shows a bare ID message — full media details shown in all cases

---

## [v1.2.4] — 2026-06-29

### Fixed — Caption pipeline never aborts on API errors (3-tier fallback)

`caption_gen.generate()` now has a guaranteed fallback chain so the pipeline always produces a caption regardless of Anthropic API availability:

1. **Primary** — Claude Haiku (unchanged, best quality)
2. **Groq fallback** — `llama-3.3-70b-versatile` via Groq (free tier); triggered on any Haiku error including credit exhaustion (`400 BadRequest`)
3. **DB fallback** — most recent caption row from the `captions` table matching `country + city` (falls back to country-only if no city match); reconstructs the full platform caption dict from stored fields

A Telegram alert fires whenever a fallback level is triggered so low-credit or Groq outages are visible without blocking the pipeline.

Only `RuntimeError` is raised if **all three** tiers fail (e.g. no prior captions exist at all and both APIs are down) — an extremely rare edge case.

---

## [v1.2.3 / fe-v1.2.3] — 2026-06-28

### Fixed — Intro/cast burned onto the live video (no frozen still, no flicker)
The intro/cast screens were rendered onto a grabbed **still frame** of the reel, so for their duration the viewer saw a frozen frame + text before the video appeared to "start"; a follow-up transparent-overlay attempt then flickered to opaque **black for ~1s** while the fade-out finished.

- Generated intro/cast are now **burned directly onto the body** in a single FFmpeg pass (`render_screens` → `burn_screens`): `drawbox` tint + `drawtext` lines gated to the intro/cast time window, each line fading via a time-based `alpha` expression. The body is the **only** video stream, so it never freezes, never flashes, and its length is unchanged.
- `bg_opacity` (default 0.20) controls the tint; set it to `0` for pure text over video. The live, moving video plays under the text the whole window.
- Asset-mode intro/cast (user-uploaded splash files) keep the clip-overlay path, unchanged.

### Added — Merge mode on the Create page + availability indicator
The Create page now builds merge montages directly (previously only Library multi-select and Telegram could).

- **`Single | Merge` mode toggle** at the top of the Create page. Single-clip flow is unchanged. Merge mode skips the strategy step → Country (required) + City/Pillar (both optional, AND-filtered) → Confirm → render.
- **Directory rules → DB filters.** Country only = all clips in that country; country+city or country+pillar narrows; all three AND together. Backed by the existing `get_country_raw_media` selection (indexed `country`/`city`/`pillar`) — no new selection logic, no disk scan.
- **Video-only.** Merge selection is `media_type=VIDEO`, so images/carousels are never pulled into a montage.
- **Live availability indicator** under the filters: counts raw VIDEO clips matching the current country/city/pillar. Red `<2` (can't merge), amber `2…min-1`, green `≥ merge.min_main_videos` (10) — so you know up-front whether there's enough footage. `Continue` is disabled below 2.
- **New endpoint** `GET /api/media/count?country=&city=&pillar=` → `{count}` (raw VIDEO, `do_not_use` excluded). Lightweight exact-count query; declared before `/{media_id}` so the literal path isn't captured as a media id.

Merge render is background (the API returns no media id up-front); the Create page matches completion on the `mrg_*` media-id prefix that merged reels emit. Single-clip behavior and its `pendingMediaId` WS filtering are untouched.

### Settings
No new keys — the `merge.*` group already governs montage behavior; the indicator reads `merge.min_main_videos` for its "enough footage" threshold.

---

## [v1.2.2 / fe-v1.2.2] — 2026-06-28

### Changed — Interleaved cuts, more variety, film grade (OpenMontage)
Four follow-up rules tightening the montage feel and look.

- **Same-video cuts are interleaved, never back-to-back** (rule 1). Sub-shots are now planned per source, the source order is shuffled, and cuts are pulled **round-robin** (pass *p* takes the *p*-th window from each video). A video's cuts always land ≥ (number of sources) apart, so the montage mixes clips instead of playing one video's 3 cuts in a row.
- **≥15 cuts** (rule 2). `merge.min_segments` default 12→**15** (clamp 15–24).
- **≥10 source videos, best-effort** (rule 3). New `merge.min_main_videos` (default **10**, clamp 2–20) — auto-select now spreads cuts across at least this many videos; a smaller country pool (e.g. Japan) simply uses everything it has and pulls more cuts per clip to still reach the target.
- **Cinematic film grade from OpenMontage** (rule 4). New `merge.grade` applies a film-look color grade to the whole montage at render time — seven pure-FFmpeg profiles ported from OpenMontage's `color_grade` (`cinematic_warm`, `cinematic_cool`, `moody_dark`, `bright_clean`, `vintage_film`, `high_contrast`, `neutral`; `colorbalance`+`curves`+`eq`). Plus `merge.grain` (subtle film noise) and `merge.vignette` (edge darkening). When a grade profile is set the **downstream LUT is skipped** for merged reels (`video_edit` checks `metadata.merge.graded`) so there's one coherent look, no double-grade.

### Settings
Four new `merge.*` keys (`min_main_videos`, `grade`, `grain`, `vignette`); `min_segments` 12→15. All surface on the Settings page via deep-merge.

---

## [v1.2.1 / fe-v1.2.1] — 2026-06-28

### Changed — Denser montage + auto disk cleanup
Seven follow-up rules for the merge montage. Three were already satisfied by existing code (see *Already wired* below); the rest tighten the auto-select montage. Backward compatible — the hand-pick path is unchanged (still one cut per chosen clip).

- **≥12 cuts per reel.** `merge.min_segments` (default **12**, clamp 12–24) is now the *floor* for auto-count; the auto ceiling rose 12→30. With the new cut defaults this yields ~13 cuts at 30s and ~20 at 45s.
- **Several sub-shots from the same video.** `merge.segments_per_clip` (default **3**, clamp 1–4) pulls that many distinct, non-overlapping sub-shots from each source video (new `_subshots()`, PySceneDetect-driven with an even-spread fallback). Auto-select now needs only `ceil(n / segments_per_clip)` videos, and a small country pool automatically pulls more cuts per clip to still reach the target — so one clip contributes several different moments.
- **Rapid cuts.** `cut_min_s`/`cut_max_s` re-defaulted **3–5s → 1.5–3s** so 12+ cuts fit a ~30s reel; target length min raised to **30s** (clamp 30–45).
- **Scratch segments deleted after render.** `merge.cleanup_segments` (default **on**) removes the per-merge work dir (`merge/<id>/seg_*.mp4`) once the final reel is written, on success *and* error paths. The final reel and source clips are never touched.
- `metadata.merge` now records `sources` (distinct source videos) and `segments_per_clip`.

### Already wired (rules confirmed, no code change)
- **Intro + cast embedded with no added time** — `screens.overlay_screens()` already composites the intro over the first seconds and the cast over the last seconds of the montage (output length == body); `video_edit` already calls it for merged reels. Just enable `intro.enabled` / `cast.enabled`.
- **Cinematic LUT grade** — `video_edit` already runs content-aware LUT selection (`color.lut_mode`) on merged reels.
- **30s minimum** — already clamped.

### Settings
Three new `merge.*` keys (`min_segments`, `segments_per_clip`, `cleanup_segments`); `cut_min_s` 3.0→1.5, `cut_max_s` 5.0→3.0. All surface on the Settings page via deep-merge.

---

## [v1.2.0 / fe-v1.2.0] — 2026-06-28

### Changed — Cinematic country montage (merge evolved)
The v1.1.0 merge stage is reshaped into a **professional, country-themed travel montage** that auto-decides everything, per `plan/MERGE_CLIPS_RULES.md`. Backward compatible — the hand-pick path and existing `merge.*` keys keep working.

- **Country-first auto flow.** Pick a **country** (now *required* for auto-select); city/pillar stay optional. The montage **mixes cities and pillars within that one country** so a reel reflects the country's overall vibe (auto path passes `pillar=None` + diverse strategy unless you narrow it).
- **Auto clip count.** `merge.auto_count` (default on) derives the number of clips from `target_duration ÷ average cut length` — no need to pick a count. An explicit count still overrides; `merge.clips_per_reel` is the fallback when auto-count is off.
- **3–5s tastes, never the whole clip.** Each clip is cut to a beat-aligned **`cut_min_s`–`cut_max_s`** (default 3–5s) best sub-shot. Target reel length re-defaulted to **30s**, clamped **20–45**.
- **Full cinematic FX** (all default-on, duration-preserving so xfade timing stays exact):
  - **Slow-mo** on alternating segments (`merge.slow_motion`, `setpts`+`trim`, factor `merge.slow_motion_factor`).
  - **Ken Burns** gentle push/pull per segment (`merge.ken_burns`, `zoompan`).
  - **Transition variety** (`merge.transition_variety`) rotates fade/dissolve/slideup/wipeleft/smoothleft/circleopen across cuts instead of one fixed transition.
  - **Beat-sync** (`merge.beat_sync`) now **default-on** — cuts snap to the music beat grid within the 3–5s window.
- **One music bed, muxed at merge time.** `merge.audio_mode="music"` (default) mutes the source clips and lays **one mood-matched track** from the music library underneath (reusing `get_track_for_pillar`), with fade in/out (`merge.music_fade_s`); `"original"` keeps the longest clip's own audio instead. The edit stage now **skips re-adding music** for `source="merge"` reels, so a merged reel always carries exactly one track.
- **UI** — `MergeClipsPanel` reshaped into **two tabs** (auto-select primary, hand-pick secondary): required country, optional city/pillar, **Auto-count** toggle (omits the count when on), a **music override** via `MusicPicker` (default "Auto — mood-matched"), a 20–45s duration slider, and a collapsed **Advanced** section (slow-mo · Ken Burns · transition variety · audio mode).
- **Settings** — nine new `merge.*` keys (`cut_min_s`, `cut_max_s`, `auto_count`, `audio_mode`, `music_fade_s`, `slow_motion`, `slow_motion_factor`, `ken_burns`, `transition_variety`); `target_duration_s` default 45→30, `beat_sync` default off→on. All surface automatically on the Settings page via deep-merge.

### Security
- A caller-supplied **`overrides.music_path`** is validated server-side (in the `create-merge` endpoint **and** in `merge_clips`) to resolve **inside `MUSIC_DIR`** — absolute escapes and `..` traversal are rejected (400). Only local library tracks are accepted as a bed.

---

## [v1.1.0 / fe-v1.1.0] — 2026-06-27

### Added
- **Multi-clip merge — stitch several clips into one 30–60s reel.** New `merge_clips.py` pipeline stage builds a longer music montage from N raw/resized clips, so short B-roll can become full-length motivation reels.
  - **Two clip sources:** *auto-select* (top-N by country/city/pillar via the existing selection helpers) and *hand-pick* (choose + reorder exact clips in the UI).
  - **Scene-aware cuts** — PySceneDetect picks the best continuous sub-shot of each clip (`merge.scene_aware`), trimmed to an even share of the target length.
  - **Crossfade transitions** — FFmpeg `xfade` chain (fade/dissolve/wipe/slide/…) between clips, whitelisted enum.
  - **Optional beat-sync** — `merge.beat_sync` aligns cuts to the music beat grid via librosa (opt-in, off by default, lazy-imported).
  - Merged reel is emitted as a new `mrg_*` media row at `status=resized`, then flows through the normal **edit → upload → schedule** pipeline (LUT, music, branding added downstream) with zero changes to those stages.
  - **Four triggers:** `POST /api/posts/create-merge` (hand-pick or auto), Telegram `/create` → "Merge N", a **Merge** panel in the Library (multi-select clips → Merge), and a settings **auto-run** gate (`merge.enabled` + `merge.auto_run`) that routes the normal create flow through merge.
  - New settings group **`merge.*`** (10 keys: enabled, auto_run, clips_per_reel, target_duration_s, selection_strategy, scene_aware, transition, transition_ms, beat_sync, min_clip_score) — surfaces automatically on the Settings page.
  - New deps: `scenedetect[opencv]`, `librosa` (both lazy-imported — non-merge code pays nothing). FFmpeg already present.
  - Heavy renders run off the event loop (`asyncio.to_thread`); clip counts and durations are clamped (2–8 clips, 15–90s) to bound CPU per request.
  - OpenMontage xfade-assembly patterns are vendored under `backend/vendor/openmontage/` (AGPLv3, isolated for audit); a built-in xfade builder is used as a fallback when not present.

---

## [v1.0.2 / fe-v1.0.2] — 2026-06-26

### Added
- **Download page — Google Drive + Google Photos import (Phase 2).** New **Google** tab on the Download page pulls videos straight from the account owner's Google account into the Library:
  - **Google Drive** — browse the owner's Drive video files (name search, thumbnails, size + duration), pick one, and the server downloads it under the size cap and indexes it as raw media.
  - **Google Photos** — uses the **Google Photos Picker API**: opens Google's hosted picker in a new tab, the user selects videos there, the page polls the session, then every picked video is downloaded and indexed automatically. (The classic Photos Library list API was restricted for third-party apps in 2025; the Picker is the supported path.)
  - **Single-account OAuth**, mirroring the YouTube uploader — one refresh token for the account owner. Mint it with `python -m backend.scripts.auth_google` (scopes: `drive.readonly` + `photospicker.mediaitems.readonly`).
  - Imported clips land in `organized/uploads/<country>/<city>/`, are ffprobe-verified, indexed as `status=raw` (`source="upload"`), and flow through the normal create-pipeline — identical outcome to Phase 1 local/URL uploads.
  - Shared **Country · City · Pillar** selector (taxonomy-suggested) applied to each import; required before import is enabled.
  - New endpoints: `GET /api/downloads/google/status`, `GET /api/downloads/google-drive/list`, `POST /api/downloads/google-drive/import`, `POST /api/downloads/google-photos/session`, `GET /api/downloads/google-photos/session/{id}`, `POST /api/downloads/google-photos/import`.
  - New env vars: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`. Settings page shows `GOOGLE_CLIENT_SECRET` / `GOOGLE_REFRESH_TOKEN` as set/unset (secrets stay in `.env`). The Google tab shows a clear setup hint until credentials are present.
  - Downloads stream to disk in 1 MB chunks with the same per-file `uploads.max_mb` cap as Phase 1; oversize rejected before/while streaming.

---

## [v1.0.1 / fe-v1.0.1] — 2026-06-26

### Added
- **Preview — per-platform publishing is now independent.** Each platform (Instagram · TikTok · YouTube) has its own Publish button and request. Publishing one platform no longer disables or hides the others — remaining platforms stay actionable until each is individually published. Per-platform busy spinner replaces the shared one.
- **Preview — "Publish to all" button.** One click publishes every active, not-yet-published platform at once (shown when more than one platform is still pending).
- **Preview — prev/next navigation.** Chevron buttons (with `position/total` indicator) step through videos in **Queue order** (`/posts?limit=500&sort=scheduled_desc`, deduped by media) without returning to the Queue page.
- **Music play/stop preview.** Inline play/stop control on each track in the **MusicPicker** dropdown (and the selected track), plus a play/stop button for the post's **current licensed track** on the Preview music line. Audio stops on navigation/unmount.

### Fixed
- **Music repeats — consecutive reels kept getting the same track.** Root cause: `get_track_for_pillar` had no cross-post memory and the scoring jitter (±0.5) was far too small to break ties against the deterministic mood/source bonuses (~5.5), so the same top-ranked track won every same-pillar reel. Added a **recently-picked cooldown** (last 10 picks tracked in `cache.json`, penalized in scoring and the local-pack fallback) and raised jitter to ±1.5. Selection now rotates across the pillar's pack while still honoring pillar/country/mood/duration matching.

---

## [v1.0.0 / fe-v1.0.0] — 2026-06-26

### Added
- **EditProgress component** — real-time edit stage visualizer in the Preview panel. Shows current pipeline stage, progress bar, and a scrollable log tail while edit/enhance runs; collapses to a status chip on completion.
- **PlatformPublishRow component** — per-platform publish status row on the Preview panel (Instagram · YouTube · TikTok). Shows success, pending, and error states with inline error message; `ig_media_id` now tracked on the post type.
- **LutPicker & MusicPicker dropdowns** — both pickers replaced with dropdown menus (click-outside to close, selected item highlighted). MusicPicker shows track name + duration; LutPicker shows LUT name + pillar tag.
- **Collapsible sidebar** — AppLayout sidebar collapses to icon-only rail with smooth CSS transition; preference persists per-session. Sidebar background switched to pure black; active nav pill uses indigo fill.
- **Download page — manual video uploads (Phase 1).** Add videos to the server without going through Instagram:
  - **Local PC upload** — drag/drop or file-picker, multi-file, streamed straight to disk (no full-file RAM buffering, supports the raised 500 MB cap).
  - **URL paste** — fetch a public **Google Drive / Dropbox / direct** video link server-side (normalizes share links to direct-download; optional `yt-dlp` fallback for Drive interstitials if installed).
  - **Per-file categorization** — Country / City (free-text combobox with taxonomy suggestions, so brand-new destinations work) + Pillar, required before submit.
  - Uploads land in `organized/uploads/<country>/<city>/`, are **indexed as `status=raw` media** (`source="upload"`, `id="up_<uuid>"`), ffprobe-probed for duration/dimensions, and flow through the normal create-pipeline. Visible in Library immediately.
  - New endpoints: `POST /api/downloads/upload` (multipart) and `POST /api/downloads/upload-url`.
  - New settings group **`uploads`**: `max_mb` (500), `allowed_types`, `auto_probe`, `url_fetch`.
  - Upload UI: per-row progress (real XHR upload progress for local files) + inline error per file.

### Changed
- **UI/UX dark-glass overhaul (all pages)** — comprehensive pass across Analytics, Statistics, Classification, Downloads, Library, Queue, Series, Pipeline pages and AppLayout:
  - **Analytics** — animated stat cards (Framer Motion stagger), custom Recharts tooltips with glass styling, dark chart theme.
  - **Statistics** — full rewrite: donut chart center label via CSS overlay (not SVG text), dark chart palette, animated card entrance.
  - **Classification** — animated stat cards, dark chart theme, motion list entries.
  - **Series** — dark glass cards, gradient progress bar, motion hover effects.
  - **Pipeline** — dark glass cards, terminal-style log panel, alpha-glass action buttons.
  - **Downloads** — dark glass cards, animated folder-tree expand, alpha-border summary tables.
  - **Library** — skeleton loading cards, glass filter selects, data-driven filter pattern; card selection state uses inline RGBA (no Tailwind 950 classes).
  - **Queue** — dark glass card containers and page header.
  - All pages use pure RGBA values instead of Tailwind `gray-950` / `gray-900` classes for consistent dark rendering.
- **Caption style: series storyteller → standalone travel guide** — `SYSTEM_GENERATE`, `SYSTEM_REFINE`, and `SYSTEM_CRITIQUE` rewritten. New voice: practical, factual, 3–5 lines. Structure: striking fact/tip → 2 info lines (culture, food, activity, or logistics) → save-worthy CTA. No episode references, no cliffhangers, no first-person narrative.
- **Series context stripped from caption prompt** — `_series_context_block` no longer injected into generate user message. Series DB records (episode_number, series_id, arc_position) preserved for future use.
- **Cliffhanger disabled** — `_ensure_cliffhanger` no longer called in `run()`. Captions are standalone per post.
- **IG hashtag cap corrected to 5** — `_PLATFORM_CAPS["instagram"]` fixed from 30→5 (per Mosseri 2026 confirmation). YouTube also updated to 5.
- **Curated pools reseeded with research-validated tags** — `_DEFAULT_POOLS` in `hashtag_engine.py` updated with 2026 best-performing travel hashtags per platform (niche > generic reach).
- **`hashtags.blend_count` default 8→3** — 3 curated reach tags + 2 LLM content-specific tags = optimal 5-tag IG set.

### Security
- **SSRF hardening on URL fetch** — `upload-url` resolves the host (all A/AAAA records) and rejects any private / loopback / link-local / reserved / multicast / metadata (`169.254.169.254`) address before requesting; only `http`/`https` schemes allowed; redirect cap + timeout. Killable via `uploads.url_fetch=false`.
- **Path-traversal guard** — country/city/filename sanitized (strip `/ \ ..`) before use as path segments; ffprobe must confirm a real video stream or the file is deleted and rejected.

### Note
- `uploads/` is excluded from the Downloads "By Country" funnel (counts shown in a dedicated Uploads stat) so manual uploads don't pollute IG-archive funnel numbers.
- Deferred to Phase 2: Google Drive OAuth picker, Google Photos. iCloud dropped (no public upload API).
---

## [v0.9.10 / fe-v0.9.10] — 2026-06-25

### Added
- **Hashtag strategy engine (`backend/pipeline/hashtag_engine.py`)** — `blend()` mixes LLM-generated tags with curated per-platform viral pools (IG/TikTok/YouTube). Picks `blend_count` curated tags, rotated by post sequence so every post differs. Applies existing denylist + dedup. Capped per platform (IG 30, TikTok 5, YT 15). Wired into `scheduler._build_platform_caption`; falls back to raw LLM tags on error. Configurable via `hashtags.curated_enabled`, `hashtags.blend_count`, `hashtags.pools`.
- **Hook-template library (`backend/pipeline/hook_library.py`)** — curated viral hook patterns per pillar × arc position (opener/build/climax/closer). `hook_block()` injects 2-3 adapted templates into the caption prompt alongside the existing feedback and trends signals. Gated by `caption.use_hook_library` (default `true`). User override via `caption.hook_templates` list.
- **Google Trends geo-targeting** — `trends_fetcher.fetch_travel_trends()` and `trends_block()` now accept a `country` name and map it to a pytrends ISO geo code (45+ countries). Cache key updated to `(date, geo)` so global and country-specific results don't collide. Activated by `caption.trends_geo` (default `true`).
- **CTA / monetization injection** — new `monetize` settings group. When `enabled`, appends `cta_text` to caption body before hashtags on configured platforms; `youtube_link` added only to YouTube description (the only platform where links are clickable).

### Tests
- `tests/test_hashtag_engine.py` — blend/cap/rotation/denylist/curated-disabled/empty-llm/unknown-platform cases (16 tests).
- `tests/test_hook_library.py` — pillar+arc lookup, `_DEFAULT` fallback, trend topic injection, user template override, hard-error guard (16 tests).
- `tests/test_trends_fetcher.py` — `_COUNTRY_TO_GEO` spot-checks, cache key tuple shape, geo pass-through, graceful pytrends absence (19 tests).
- `tests/test_scheduler_cta.py` — CTA enabled/disabled, youtube_link platform isolation, platform filter, empty CTA guard, settings-error resilience (14 tests).

---

## [v0.9.9 / fe-v0.9.9] — 2026-06-22

### Fixed
- **`classify_vision` skipped every clip (`scored 0, skipped N`)** — `_video_path()` ran `os.path.exists()` on `local_path` verbatim, but `local_path` is stored **relative to `ORGANIZED_DIR`** (see `index_content.py`). Inside the container that relative path never resolved, so every un-scored clip was silently skipped and no footage was ever hook-scored. It now re-anchors a relative `local_path` to `ORGANIZED_DIR` (matching `resize_clips`), then falls back to `reel_ready_path` and the `r2_url` HTTP stream.
- **Silent skips were undiagnosable** — an empty run logged nothing, so the server logs showed no cause. `run()` now logs a per-skip reason (`local_path`/`reel_ready_path`/`r2_url`) and an INFO summary at the end; a clip with no extractable frames is now a skip, not a failure.

### Added
- **Nightly vision backfill at 03:00** — a new `nightly_vision` APScheduler job runs `classify_vision` once a night at 03:00 in the `schedule.timezone` (falls back to UTC on a bad tz), backfilling `hook_score` + `pillar` on un-scored footage. Gated by `vision.enabled`; runs in a thread executor so it never blocks the event loop; `misfire_grace_time=3600` so a busy/restarting worker still runs within the hour.
- **`vision` settings group extended** — `provider` (`auto`|`groq`|`local`, default `auto`) and `nightly_limit` (default 50) control the nightly run. Surfaced via the per-group settings deep-merge.

### Tests
- `tests/test_classify_vision.py` — `_video_path` relative-resolution / absolute / `r2_url`-fallback / none cases, plus the `vision.enabled=False` skip path.

---

## [v0.9.8] — 2026-06-21

### Fixed
- **Daemon `_auto_publish` crash on corrupted HTTP/2 connection** — a reused Supabase httpx client occasionally raised `httpx.LocalProtocolError: Received pseudo-header in trailer`, killing the auto-publish tick (and `series_builder`). `db_retry()` now treats `LocalProtocolError` / "pseudo-header in trailer" as transient: it resets the cached client and retries, matching the existing `RemoteProtocolError` recovery path.
- **YouTube playlist add aborting on transient 409** — `_add_to_playlist` failed permanently on `409 SERVICE_UNAVAILABLE` ("The operation was aborted"). It now retries up to 3× with backoff on transient `SERVICE_UNAVAILABLE`/`backendError`/aborted errors before giving up; the existing 404 cache-clear path is preserved.

### Tests
- `tests/test_db_lookups.py` — added `db_retry` cases: recovers from `LocalProtocolError` (reset + retry) and re-raises non-transient errors.

---

## [v0.9.7] — 2026-06-20

### Added
- **Content-aware colour grading (LUT selection)** — the edit stage now picks the best-fitting LUT per clip instead of the flat 6-entry pillar map. New `backend/pipeline/lut_select.py` runs a layered cascade gated by the new `color` settings group: `fixed` → `vision` (opt-in) → `mood` → `pillar`, always degrading to the legacy `PILLAR_LUT` floor so it never grades worse than before and never raises into the edit.
  - **Curated cinematic LUT library** — vendor `.cube` files staged in `assets/cubes/` are curated into `assets/luts/cinematic/` and described by `assets/luts/catalog.json` (mood + pillar tags). Legacy `warm/cool/vintage.cube` are kept as the fallback floor.
  - **`backend/scripts/curate_luts.py`** — a manual, CPU-heavy script (not run by the pipeline) that walks the staging dir, drops invalid/truncated cubes via `valid_cube()`, copies a curated keep-list into `cinematic/`, and emits `catalog.json`. `--dry-run` by default; `--apply` to write; `--ffmpeg-test` to smoke-test each keeper.
  - **Vision override** — when `color.use_vision` is on (or mode = vision), reuses `classify_vision` to pick a LUT from the frames, preferring a cached `media.metadata.vision.pillar` to avoid a second Groq call. Off by default.
  - **Mood override** — reuses `music_mood.mood_from_text()` so an "epic" caption gets an epic-tagged LUT, matching the existing mood-matched-music pattern.
- **`color` settings group** (Design → Color Grade tab): `lut_mode` (`pillar`|`mood`|`vision`|`fixed`, default `pillar`), `fixed_lut`, `use_vision`, `intensity` (advisory only — full LUT applied, no opacity blend in v1).
- **`GET /api/assets/luts`** now returns catalog metadata (`tags`, `pillars`, `intensity`, `source`, `dir`) and the curated `cinematic/` set alongside the legacy LUTs. The LUT picker chips show mood/topic tags.

### Fixed
- **Manual LUT pick in the Preview edit drawer now applies** — `picks.color_grade.lut` was sent by the frontend but ignored by the backend. `edit.py` now threads it through `orchestrator.run(lut_override=…)` → `video_edit.edit_single`, where `select_lut()` path-guards it (rejects traversal / missing files) and lets it override automatic selection.

### Security
- `select_lut._safe_lut()` validates any settings/catalog/manual LUT path resolves under `LUTS_DIR` before use (path-traversal guard).

## [v0.9.6] — 2026-06-20

### Fixed
- **Edit stage crash: `lut3d ... Unexpected EOF`** — the shipped `assets/luts/*.cube` files were stubs: each declared `LUT_3D_SIZE 17` (requires 17³ = 4913 RGB rows) but contained only ~306 rows plus a literal `// ... 306 more lines` placeholder. FFmpeg's `lut3d` filter reads the declared size, hits EOF mid-data, and aborts the whole `filter_complex`, failing every edit for pillars that map to a LUT. The render retry only stripped `zoompan`, so it failed again with the LUT still in the chain. Three-part fix:
  - **Regenerated complete LUTs** — `warm.cube` / `cool.cube` / `vintage.cube` are now full 16³ (4096-row) 3D LUTs with real per-channel grades. Colour grading actually works for the first time.
  - **`valid_cube()` guard** — `video_edit.apply_lut()` now validates that a `.cube` has exactly `size³` data rows before adding `lut3d`; a truncated/stub/missing file is skipped (un-graded reel still renders) instead of crashing.
  - **Progressive render fallback** — `VideoEditor.render()` now strips `zoompan` *then* `lut3d` on failure (was zoompan-only), so a single bad filter degrades the reel instead of failing the edit.
- **500 on `POST /api/posts/{id}/reject` (and any stale id)** — `get_post_by_id` / `get_media_by_id` used PostgREST `.single()`, which raises `APIError PGRST116` ("Cannot coerce the result to a single JSON object") on 0 rows. A reject/approve/publish on an already-deleted post returned HTTP 500 instead of a clean 404. Both lookups now use `.maybe_single()` and return `None` on 0 rows → routes raise the intended 404.

### Tests
- `tests/test_db_lookups.py` — pins `.maybe_single()` behaviour: missing id → `None` (never raises); also asserts `single()` is not used.
- `tests/test_video_edit_lut.py` — `valid_cube` accepts complete / rejects stub, missing, empty; `apply_lut` skips invalid LUTs; `render` strips `lut3d` on failure; shipped `assets/luts/*.cube` are asserted complete.
- `requests/api.http` — manual smoke collection asserting every endpoint returns 2xx/4xx (never 500), including unknown-id 404 regression guards.

---

## [v0.9.5] — 2026-06-19

### Fixed
- **1:40 video output bug** — `zoompan d={fms}` in `_animation_filters` (zoom + ken_burns branches) treated `d` as "output frames per input frame" rather than total output frames. On a 60-frame intro clip with `fms=60`, this emitted 3,600 frames (~100 s). Fixed by `d=1` (one output frame per input frame; zoom animates via the `on` counter). Same fix applied to the parallel `zoompan` call in `_build_generated_clip` zoom branch.
- **`_get_duration` returning None for libx264 MP4s** — probe used `-show_entries stream=duration` which returns `N/A` when duration lives only in the container header (common for files encoded by this pipeline). Switched to `-show_entries format=duration` (container-level, always present). Prevents `body_dur=0.0` fallback that silently skipped the `-t` output clamp and mispositioned the cast overlay at t=0.
- **Silent probe failure** — `overlay_screens` now logs a WARNING when `_get_duration` returns None so operators can detect the failure instead of receiving a wrong-length reel with no diagnostics.
- **Dead `fms` variable** — removed `fms = int(d * _FPS)` from `_animation_filters`; no branch referenced it after the `d=1` fix.

---

## [v0.9.4 / fe-v0.9.4] — 2026-06-19

### Added
- **6 new animation types + random mode** for intro & cast screens: `slide` (bottom-to-top reveal), `blur` (soft glow fade), `wipe` (left-to-right reveal), `ken_burns` (slow zoom + sinusoidal pan). Plus `random` — pipeline picks a different animation on each reel. All implemented via FFmpeg filter graph alpha compositing; Design page live preview shows matching CSS keyframes. Set `intro.animation` / `cast.animation` to any of: `none`, `fade`, `zoom`, `slide`, `blur`, `wipe`, `ken_burns`, `random`.

### Changed
- **Intro & cast screens now overlay the video instead of prepending/appending** — replaced `concat_screens` (sequential clip concat) with `overlay_screens` (FFmpeg filter_complex overlay). Body video plays from second 0; intro composites on top for the first `intro.duration_s` seconds, cast composites over the final `cast.duration_s` seconds. Total reel length equals the body duration — no extra dead time before the content starts.
- **All animations are now flicker-free** — animations previously baked into the standalone clip (fade from black) are replaced with alpha-channel compositing in the filter graph. The body video is always visible underneath; the overlay fades in/out via `yuva420p` alpha expressions, eliminating the dark flash at the start and end of each screen.

### Fixed
- **Cast overlay never appearing** — the previous `-itsoffset` approach shifted the cast clip's PTS at the demuxer level, causing FFmpeg to seek `cast_start` seconds *into* the 2.5 s cast clip (past its end). Fixed with `setpts=PTS+cast_start/TB` in the filter graph so the clip reads from frame 0 at the correct output time.

---

## [v0.9.2 / fe-v0.9.2/ v0.9.3 / fe-v0.9.3] — 2026-06-19

### Added
- **Video frame backdrop on intro & cast screens** — generated screens now grab a real frame from the reel video instead of rendering against a solid black canvas. Intro grabs at `ss=0.5 s`; cast grabs at `ss=2.0 s` (deeper into the clip for visual variety). The `bg_color`/`bg_opacity` overlay is composited on top of the frame so any opacity < 1.0 lets the footage show through. New `_grab_frame()` helper in `screens.py`; `_build_generated_clip` gains an optional `source_frame` parameter.
- **`_compute_drawtext_items` layout engine** — replaces the old fixed three-line `y*0.38/0.50/0.62` heuristic with a proper vertical centering calculation that accounts for per-element `bottom_padding`, line height, and inter-element gap.

### Changed
- **`bg_opacity` default lowered to `0.20`** across all intro and cast defaults (`settings.py` DEFAULTS, `IntroSection.tsx`, `CastSection.tsx`, `ScreenPreview.tsx`). At 0.20 the grabbed video frame shows through at 80 %, giving screens a cinematic look. Existing installs with `bg_opacity=1.0` in the DB keep their stored value — update via the Design page slider to opt in.
- **`intro.duration_s` default** changed from `2.0 s` to `1.5 s`; **`cast.duration_s`** from `2.5 s` to `1.5 s`.

---

## [v0.9.1 / fe-v0.9.1] — 2026-06-18

### Added
- **Per-element bottom padding** — every text element on Intro and Cast screens (header, sub-header, country, city, pillar, handle / CTA, episode) now has its own configurable bottom padding (px). Previously only sub-header had this control. New settings keys: `intro.header_bottom_padding`, `intro.country_bottom_padding`, `intro.city_bottom_padding`, `intro.pillar_bottom_padding`, `intro.handle_bottom_padding`; and equivalent `cast.*` keys.
- **Drag-to-reorder element cards** — Intro and Cast element cards are now full drag-and-drop sortable via `@dnd-kit`. Arrow buttons remain as keyboard-accessible fallback. Drag handle (⠿ icon) appears on card header.
- **Two-column Design page layout** — config panel scrolls on the left; a large sticky 9:16 live preview occupies the right column. Preview hot-reloads instantly as settings change (no save needed).
- **Animated live preview** — Intro/Cast 9:16 preview now shows the configured animation (`fade`/`zoom`/`none`) looping in real-time with the bundled travel-scene backdrop. Multi-line text, per-element colors, font sizes, and bottom padding all reflect live.
- **Branding tab preview** — Video Branding tab also gets the right-column sticky preview with the same backdrop (extracted from the old inline mockup).

### Fixed
- **Intro/Cast screens not appearing in final video** — root cause traced to the resize→enhance source-resolution cascade erroring the edit stage before the concat block ran. Three hardening fixes: (1) resize now self-heals clips where `reel_ready_path` file is missing on disk by regenerating the `_9x16.mp4`; terminal statuses (`posted`, `uploaded`, `scheduled`, `preview`, `rejected`) are excluded from self-heal so published clips are never re-queued. (2) enhance source-not-found reset now also clears the stale `reel_ready_path` DB pointer via `update_media` instead of `update_status`. (3) `reel_ready_path` pointer cleared atomically with the status reset so the edit stage never trips on a stale path.
- **Duplicate video files accumulating in `reels_ready/`** — edit stage now deletes its source input (`_enhanced.mp4` or `_9x16.mp4`) after writing the canonical edited reel to the DB. Pre-concat body `_edited.mp4` is also deleted when screens produce a `_final.mp4`. Net result: one file per clip instead of up to four.
- **`int(None)` crash in screens.py** — all `*_bottom_padding` reads from settings now use `cfg.get(key) or default` so an explicit DB `null` (from a manual edit or migration) does not raise `TypeError`.
- **resize self-heal guard now correctly protects `_9x16.mp4`** — the deletion guard in `video_edit.py` now checks `reel_path` against both `output_path` and `final_path` (set union) so the source resize file is never deleted regardless of whether the enhance stage ran.

---

## [v0.9.0 / fe-v0.9.0] — 2026-06-17

### Added
- **Design page** — new `/design` route with three tabs (Video Branding · Intro Screen · Cast Screen). Branding config moved here from Settings; each tab has a live 9:16 CSS preview. Nav entry added.
- **Intro (Splash) screen** — optional 1080×1920 clip prepended to every reel. `generated` mode renders a text card (location · pillar, @handle) via FFmpeg `lavfi color` source with configurable `none`/`fade`/`zoom` animation; `asset` mode normalizes any uploaded image or video. Duration 1–4 s, all controls in Design → Intro Screen tab. New settings group `intro.*` (default `enabled=false`).
- **Cast (Outro) screen** — optional outro appended to every reel. Supports CTA text, location recap, and series next-episode hint. Same generated/asset dual-mode. Duration 1–5 s. New settings group `cast.*` (default `enabled=false`).
- **`backend/pipeline/screens.py`** — new module: `build_intro_clip`, `build_cast_clip`, `concat_screens`. Concat uses `filter_complex concat=n=N:v=1:a=1` (robust to param drift). Both screen builders degrade gracefully (return `None`) so pipeline never fails due to a missing font or bad asset.
- **Intro/outro asset upload** — `GET /api/assets/intros`, `POST /api/assets/intros/upload`, `GET /api/assets/outros`, `POST /api/assets/outros/upload` (50 MB cap, auth-gated, stored in `assets/intros/` and `assets/outros/`, served at `/static/assets/intros|outros/`). New `INTRO_DIR`/`OUTRO_DIR` path constants.
- **`ig_handle` single source of truth** — both intro and cast screens pull `@handle` from `branding.ig_handle` so it never needs to be set in two places.

### Changed
- **Branding moved to Design page** — `branding.*` controls removed from Settings page and now live exclusively under Design → Video Branding tab. Settings group and backend keys unchanged.

---

## [v0.8.0 / fe-v0.8.0] — 2026-06-16

### Fixed
- **Enhance stage self-heals missing resize file** — when `_9x16.mp4` is missing on disk (e.g., after a purge) but `status=resized`, enhance now resets status to `raw` instead of permanent `error`, letting the resize stage regenerate the file on the next pipeline run.
- **Duplicate `_9x16.mp4` + `_enhanced.mp4` files eliminated** — enhance now deletes the `_9x16.mp4` intermediate immediately after writing the canonical `_enhanced.mp4`, keeping `reels_ready/` under its 5 GB cap. The `_enhanced.mp4` remains the sole file for each clip.
- **FFmpeg self-overwrite on re-enhancement** — re-running enhance on an already-enhanced clip (after `_9x16.mp4` was deleted) no longer corrupts `_enhanced.mp4`; output is written to a temp file and atomically renamed.

### Added
- **`diverse` auto-create strategy** — new `pipeline.auto_create_strategy="diverse"` picks a random unposted clip across all countries, with a configurable country cooldown (`selection.country_cooldown_posts`, default 5) to prevent the same country from being repeated. Switch the daemon to this strategy to fix Turkey-dominant queues.
- **Classified-only clip selection** — new `selection.require_classified=true` (default on) restricts auto-create to clips that have all three classification fields set: `pillar`, `hook_score`, and `country`. Falls back to the full pool if no fully-classified candidates exist, so the queue never starves during vision backfill.
- **Vision classifier r2_url fallback** — `classify_vision` nightly run now falls back to the R2 URL when local files have been purged, fixing the ~35/50 "skipped" entries in vision-nightly.log.
- **Branding font size control** — new `branding.font_size` setting (px; 0 = auto, scales proportionally with `bar_height`) lets you pin bar text to a specific size. Clamped to `bar_height - 2` so text never overflows the bar.

---

## [v0.7.0 / fe-v0.7.0] — 2026-06-15

### Fixed (post-deploy patches)
- **Branding overlay font fallback** — `fonts-liberation` now installed in the Docker image; overlay falls back to Liberation Sans when custom `PlayfairDisplay-SemiBold.ttf` is absent from the bind-mounted assets dir. Rsync LUTs too: see COMMANDS.md.
- **422 on POST /pipeline/\*** — `api.post()` with no body was sending `Content-Type: application/json` but no body, causing FastAPI 422. Fixed: POST/PUT now always send at least `{}`.
- **QualityRejected no longer retried** — orchestrator now aborts immediately on quality rejection instead of retrying 3×.
- **Selection gate data** — `index_content` now probes up to 200 unscored VIDEO files per run via ffprobe and writes `duration_s`, `width`, `height` to DB so `min_duration_s`/`min_short_side` filters have actual values to act on.
- **`require_manual_for_pillars` now enforced** — `approval.require_manual_for_pillars` was stored in settings but never checked; daemon now skips auto-publish for posts whose media pillar is in the list.
- **ffmpeg stderr now logged** — render failures previously swallowed the ffmpeg stderr; it is now emitted to the server log so branding/LUT/filter errors are diagnosable.

### Added
- **Video branding overlay** — every finished reel and its R2 thumbnail now gets a full-width bottom bar baked in via FFmpeg, showing `City, Country` and `@handle` in Playfair Display serif. Fully configurable via the new `branding` settings group with a **live CSS preview** in the Settings UI. Bar colors, opacity, height, top/bottom position, and which side each element appears on are all admin-controlled in real time. Defaults **off** — set your handle and enable when ready. New keys: `overlay_enabled`, `ig_handle`, `bar_height`, `show_on_thumbnail`, `bar_bg_color`, `text_color`, `bar_opacity`, `bar_position`, `location_side`, `handle_side`. New shared helper `backend/pipeline/overlay.py`; `brand_thumbnail()` in `thumbnail.py`; `FONTS_DIR` in `config.py`.
  - **Deploy step required:** place `PlayfairDisplay-SemiBold.ttf` (Google Fonts, SIL OFL 1.1) at `/srv/travel-cms/assets/fonts/PlayfairDisplay-SemiBold.ttf` on the CX33 host (the `assets/` dir is bind-mounted, shadowing the Docker image). Without the font the overlay is silently skipped and a warning is logged.
- **Zernio integration** — Instagram and TikTok now publish via Zernio (`backend/pipeline/zernio_publish.py`). When `ZERNIO_API_KEY` is set, both platforms use Zernio's audited client (bypasses Meta app review / TikTok audit). Falls back to native publishers if key is absent. Zernio post IDs stored in new `zernio_ig_id` / `zernio_tt_id` columns; errors in `zernio_ig_error` / `zernio_tt_error`. New env vars: `ZERNIO_API_KEY`, `ZERNIO_IG_ACCOUNT_ID`, `ZERNIO_TT_ACCOUNT_ID`. Migration `012_zernio_ids.sql`.
- **Per-platform Telegram approve buttons** — the preview push now shows individual `📸 Instagram`, `🎵 TikTok`, and `▶️ YouTube` buttons alongside `✅ All Platforms` and `❌ Reject`. Tapping a platform button publishes to that platform only (`publish_post(..., platforms_override=[platform])`), letting you approve platforms independently.
- **DB:** `posts.zernio_ig_id`, `zernio_ig_error`, `zernio_tt_id`, `zernio_tt_error` columns (migration `012_zernio_ids.sql`).

---

## [v0.6.0 / fe-v0.6.0] — 2026-06-14

### Added
- **Zernio integration** — Instagram and TikTok now publish via Zernio (`backend/pipeline/zernio_publish.py`). When `ZERNIO_API_KEY` is set, both platforms use Zernio's audited client (bypasses Meta app review / TikTok audit). Falls back to native publishers if key is absent. Zernio post IDs stored in new `zernio_ig_id` / `zernio_tt_id` columns; errors in `zernio_ig_error` / `zernio_tt_error`. New env vars: `ZERNIO_API_KEY`, `ZERNIO_IG_ACCOUNT_ID`, `ZERNIO_TT_ACCOUNT_ID`. Migration `012_zernio_ids.sql`.
- **Per-platform Telegram approve buttons** — the preview push now shows individual `📸 Instagram`, `🎵 TikTok`, and `▶️ YouTube` buttons alongside `✅ All Platforms` and `❌ Reject`. Tapping a platform button publishes to that platform only (`publish_post(..., platforms_override=[platform])`), letting you approve platforms independently.
- **DB:** `posts.zernio_ig_id`, `zernio_ig_error`, `zernio_tt_id`, `zernio_tt_error` columns (migration `012_zernio_ids.sql`).
- **Video selection quality gate** — clip selection (`get_raw_media_for_create` + `get_next_story_episode`, both Supabase & SQLite) now skips clips that fail the new `selection` rules: `min_duration_s` (10), `min_short_side` (720px), `min_hook_score` (0=off), `min_quality_score` (0=off). Null-safe — a clip is only rejected when the field is present and below threshold, so missing data never starves the queue. Every skip is logged with a reason.
- **Blur/shake quality probe** — new `backend/pipeline/quality_probe.py` runs as the **first** create-pipeline stage. Two cheap FFmpeg passes (edgedetect→signalstats sharpness, signalstats YDIF stability) produce `blur_score`/`shake_score`/`quality_score` (0–1), stored on the media row. At the default `min_quality_score=0` it only measures; once a threshold is set, a failing clip is flagged `do_not_use=1` and the pipeline aborts before any resize/enhance/edit. Backfill: `python -m backend.pipeline.quality_probe --backfill`.
- **Flag-unusable sweep** — new `backend/pipeline/flag_unusable.py` permanently shelves (`do_not_use=1`) raw clips failing the hard present-field rules (too short / too low-res). Idempotent; `--dry-run` first.
- **Series page** — new `/series` view + `GET /api/series` endpoint: every country journey with a posted/total progress bar, status, and the next pickable episode. "Create next" runs the story pipeline for that country in one click.
- **DB:** `media.quality_score`, `blur_score`, `shake_score` columns (migration `011_quality_probe_scores.sql` + SQLite schema/migration list).

### Changed
- **Series titles** — brand-new multi-day series are now named `"N Days in {country}"` (single-day fall back to `"{country} — Mon Year"`); user/LLM-edited titles are still preserved.
- **Arc-aware caption hooks** — caption generation now uses the cluster-relative `series_arc_position` (opener/climax/closer) instead of country-lifetime episode arithmetic, so mid-archive series get proper opener/closer framing and the correct cliffhanger vs wrap-up CTA.
- **Logging** — clearer, grep-able lines across the edit stage (start/end + fix hints), selection (pick/skip reasons), and the new probe/flag scripts.

### Settings
- New `selection` keys: `min_duration_s`, `min_short_side`, `min_hook_score`, `require_video_only`, `quality_probe_enabled`, `min_quality_score` — all surfaced in the Settings page with field hints and documented in the Docs page + CLAUDE.md.

---

## [v0.5.0 / fe-v0.5.0] — 2026-06-13

### Changed
- **Library pagination** — "Load More" replaced with offset-based Prev/Next pages; page size 24.
- **Queue pagination** — client-side numbered page buttons added; no more unbounded list load.
- **API response caching** — Analytics, Statistics, and Classification pages now use `staleTime: Infinity` via `useApi`; data never re-fetches on tab switch. `useApi` hook accepts `options.staleTime` to let callers override.

### Fixed
- **Media `status` not set to `posted` after publishing** — `publish_post()` now calls `update_media(media_id, {status: "posted"})` after successful IG publish; Analytics "Posted" count was always 0 before this fix.
- **`hashtags_en_b` missing from SQLite schema** — column added to `db.py` `CREATE TABLE` block and migration list; Supabase A/B hashtag variant field was silently absent in local/fallback mode.
- **`save_caption()` missing fields** — `pillar`, `country`, `city`, and `context` fields are now written to the captions table on every `POST /api/captions/generate` call.
- **Analytics timeseries missing columns** — `plays`, `engagement_rate`, and `platform` columns added to the timeseries Supabase query in `analytics.py`.
- **FUNNEL_STAGES missing `enhanced`** — `statistics.py` and `downloads.py` funnel arrays now include the `enhanced` stage so the pipeline funnel chart renders the full state machine.
- **`video_edit.py` silent failures** — `edit_single()` now catches exceptions, logs the full traceback, and persists `status=error` + `error_message` to the media row so failures are visible in the Library.
- **Preview — AI Regen drops hashtags** — `regenCaption` now calls `PUT /posts/{id}` with `caption`, `hashtags_en`, and `hashtags_ar` from the generate response; previously only `caption` was saved, silently discarding new hashtag sets.
- **Preview — AI Enhancement video stale** — `doEnhance` now injects the updated media object returned by the synchronous `POST /media/{id}/enhance` endpoint directly into the TanStack Query cache via `setData`, then increments `videoKey` to remount `<video>` — no polling, no extra GET.
- **Preview — Quick flags no visual feedback** — active flags now render as amber `⚑ label` chips overlaid at the bottom of the video player (`absolute bottom-14`, `pointer-events-none`); chips appear/disappear in real time as flags are toggled.
- **Preview — `saveFlags` swallows errors** — wrapped in try/catch; failures now surface via `toast.error`.

---

## [v0.4.0 / fe-v0.4.0] — 2026-06-12

### Added
- **Free video-quality chain (Enh K)** — `video_edit.py` gains a CPU-only FFmpeg enhancement pass at the edit stage: `hqdn3d` denoise (before motion so zoom doesn't amplify grain) → Ken Burns → LUT → contrast-adaptive sharpen (`cas`) → optional motion-compensated frame interpolation (`minterpolate`, opt-in). Encode bumped to CRF 20 / preset `medium`. Resize now scales with the sharper `lanczos` filter. No GPU, no API cost.
- **Quality settings** — new `video` group keys: `enhance_quality`, `denoise`, `denoise_strength`, `sharpen`, `sharpen_amount`, `crf`, `preset`, `smooth_motion`, `smooth_fps`. The `video` group is now surfaced in the Settings UI (was defined but hidden).
- **Caption Groq drafter (Enh L)** — `caption.draft_with_groq` (default off) drafts the caption set on the free Groq tier, then the existing Haiku self-critique pass polishes the hooks — drives caption spend toward $0. Falls back to full Haiku generation on any Groq error.
- **Hashtag denylist (Enh L)** — `hashtags.blocked` strips over-saturated / shadow-ban-prone tags (and duplicates) from every generated English hashtag set; empty list uses a built-in default denylist.

### Docs
- New plan: `plan/AI_TOOLS_AND_LLM_MODELS.md` — June-2026 AI tools/LLM research, pricing, CX33 local-model feasibility verdict, and the free enhancement roadmap.
- Docs page + Settings reference updated for the video-quality chain and the new caption/hashtag toggles.

---

## [v0.3.0 / fe-v0.3.0] — 2026-06-10

### Added
- **Framer Motion animations** — staggered stat cards on Analytics, animated NotificationBell dropdown + badge, TaskCenter slide-down panel, indigo-purple-pink gradient GlobalProgressBar
- **Library page UI overhaul** — default status filter changed from `uploaded,posted` to `all`; visual refresh throughout
- **Queue page overhaul** — `useApiMutation` hook, status filters, bulk approve, grid/list toggle; default sort changed to `scheduled_desc` (newest first)
- **Settings page overhaul** — field hints, collapsible groups, new settings groups
- **Create page hardening** — WS `pipeline_complete`/`pipeline_failed` handlers now filter by `pendingMediaId` to ignore cross-job events; `ErrorStep` component handles known pipeline error cases
- **TaskCenter** — shows latest posted video (uses `sort=scheduled_desc`); `useSyncExternalStore` hooks for task store
- **`useApiMutation`** — TanStack Query wrapper for API mutations; replaces ad-hoc fetch mutation calls
- **Posts sort direction** — `GET /api/posts` accepts `sort=scheduled_asc|scheduled_desc`; `db.get_posts()` accepts `desc` param
- **Auth test suite** — unit tests for HS256 + ES256 token verification and token rejection cases
- **Posts + Security test suites** added
- **Country migration script** (`backend/scripts/migrate_country.py`) — structured JSON parse (not regex), batch Supabase country update, per-row `local_path` update only where needed, CLI input validation with path-traversal guard
- Music scraper (`backend/scripts/scrape_music.py`) — multi-source tiered download from Jamendo, Pixabay (click-and-intercept), and Chosic (Playwright)
- Smart track matching in `music_fetcher.py` — local-first three-tier architecture (Pixabay/Chosic → local Jamendo → Jamendo API); source-aware scoring (+1.5 local, +0.5 Jamendo)
- `audio_probe.classify()` now returns `duration` field for all clips (including silent/no-audio)
- `--clip-len` CLI flag on `music_fetcher` for manual selector testing
- 265 royalty-free tracks seeded across all 6 content pillars

### Changed
- **WebSocket JWT auth** moved from URL query param to first message body — keeps token out of server access logs
- **JWKS client cache** replaced `lru_cache` with URL-keyed dict — fixes cache poisoning in test isolation
- **Auth module** supports both HS256 (legacy) and ES256 (Supabase JWKS) JWT algorithms
- `get_track_for_pillar()` refactored: Jamendo API only fires when no local file found on disk
- Migrations 007 + 008: constraint drop simplified to `DROP CONSTRAINT IF EXISTS` — idempotent and safe on re-run

### Fixed
- **Soft-delete** (`status='deleted'`) was blocked by missing value in `media_status_check` CHECK constraint → added in migration 008
- **`taskStore.upsertTask`** spread order fixed — `startedAt` is now immutable once set; partial updates no longer reset it
- **`migrate_country.py`** manifest update switched from regex string replace to structured JSON parse — prevents partial/corrupt rewrites

---

## [v0.2.1 / fe-v0.2.1] — 2026-06-09

### Fixed
- Task store snapshot over-saving optimized; snapshot only written on actual state change

---

## [v0.2.0 / fe-v0.2.0] — 2026-06-09

### Added
- **Task Center** — persistent header component tracking all background pipeline tasks with live status indicators
- **TanStack Query** — replaced ad-hoc fetch logic; provides request caching, deduplication, and in-flight indicators across the frontend
- Shake detection + stabilization control in media processing pipeline (configurable per-clip)

### Changed
- Task store snapshot management optimized — fewer writes, debounced persistence

---

## [v0.1.5 / fe-v0.1.5] — 2026-06-08

### Added
- Jamendo API integration for background music sourcing with local pack fallback
- Queue page filtering and sorting (by pillar, status, date)
- Refined media selection and thumbnail extraction logic

### Fixed
- Python healthcheck in Dockerfile — `curl` missing from slim image
- CORS tests and post approval logic refactored

---

## [v0.1.4] — 2026-06-08

### Added
- Enhanced deployment process; improved DB connection handling (HTTP/2 drop guard)

---

## [v0.1.3] — 2026-06-08

### Added
- Audio processing enhancements and video editing capability improvements
- `deleted` status added to media state machine; edit-post flow updated
- Series rebuilding functionality added to daemon
- Enhanced error handling in edit-post and video editing pipeline

---

## [v0.1.2] — 2026-06-07

### Added
- Posting scheduler (`scheduler.py`) — multi-platform enqueue/publish/cancel/reschedule
- Auto-create scheduler, continuous episode numbering, bilingual YT/TT metadata, YouTube playlist support
- Classify stage wired into pipeline orchestrator
- Video enhancement stage (`enhanced` status) with FFmpeg filters and related tests
- Version info endpoint (`/api/health` extended) + frontend build metadata injection
- `retry-youtube` endpoint — re-upload to R2 then retry YouTube Short

### Fixed
- Daemon misses approved posts — tick logic corrected
- CORS on 500 responses
- Video missing in Preview panel
- `posts_status_check` constraint violation on approve (status must not be set to `approved`)
- Relative `local_path` resolved to absolute in `resize_clips`
- Frontend release guard — safe Docker prune in CI

---

## [v0.1.1] — 2026-06-07

### Added
- Statistics page + `ServerStatusBadge` component
- Docs page + enhanced `LogFooter`
- Delete post functionality (`/api/posts/{id}` DELETE)
- Logging throughout media processing pipeline

### Fixed
- WebSocket handling and broadcast task management stabilized
- Taxonomy API response unwrapping in Library country dropdown
- VIDEO-only filter in series picker; skip non-VIDEO in `series_runner`
- `timestamp` field handling in `PipelineRun` interface

---

## [v0.1.0] — 2026-06-06

### Added
- **Phase 7** — YouTube-only platform switch; `instagram_enabled` setting
- **Phase 6** — Media library: new filters (pillar, country, status) and sorting options
- **Phase 5** — Supabase pagination for media loading
- **Phase 4** — Telegram notifications for post publishing and approval events
- **Phase 3** — Slot-based scheduling for post approval and publishing windows
- **Phase 1+2** — R2 storage management + cleanup scripts
- New reel templates: beach, food, nature pillars
- `opt-in` local media serving in production via `SERVE_LOCAL_MEDIA`
- OWASP security best practices + pytest configuration

### Fixed
- Phase 0: post rejection status set to `cancelled` (was `rejected`); approval logic corrected
- Supabase queries guarded against HTTP/2 connection drops
- Frontend media preview URLs built from relative `local_path`
- Groq classify backfill: paginate all raw rows; stop cleanly on daily cap
- Supabase column names for analytics and `pipeline_runs` queries
- `VERCEL_TOKEN` env var passed correctly in CI; redundant build step dropped
- ES256 JWT verification via Supabase JWKS
- production domain added to CORS allow_origins

---

## [v0.0.30] — 2026-06-06

### Added
- Create page and navigation update
- Organized media breakdown by country in Downloads page
- Pipeline run completion timestamps

### Fixed
- Supabase index manifests + paginate `get_distinct`
- Frontend release workflow; Downloads API fixes

---

## [v0.0.25 – v0.0.29] — 2026-06-04 – 2026-06-05

### Added
- Multi-platform publish: YouTube Shorts (`youtube_publish.py`) + TikTok Direct Post (`tiktok_publish.py`)
- Telegram bot full implementation — preview push, `/create` state machine, inline Approve/Reject/Reschedule buttons
- Daemon (`daemon.py`) — APScheduler auto-publish job in FastAPI lifespan (single worker enforced)
- WebSocket real-time pipeline events (`/ws/pipeline`)
- Settings page — grouped settings form with secrets status map
- Analytics page — overview, pillars, timeseries

---

## [v0.0.20 – v0.0.24] — 2026-06-03 – 2026-06-04

### Added
- Caption generation pipeline (`caption_gen.py`) — Claude Haiku, always EN+AR output
- Caption history endpoint (`/api/captions`)
- Media edit drawer — AI edit dispatch via Haiku tool-use (`/api/posts/{id}/edit`)
- MusicPicker + LutPicker components; `/api/assets/music` + `/api/assets/luts` endpoints
- Supabase-first / SQLite fallback DB abstraction (`db.py`)
- Supabase JWT auth middleware (`auth.py`)

---

## [v0.0.15 – v0.0.19] — 2026-06-01 – 2026-06-02

### Added
- `classify_groq.py` — Groq Llama 3.3 70B pillar/country tagger (new downloads only)
- `resize_clips.py` — FFmpeg 9:16 crop stage
- Queue page — approve/reject/reschedule + live WebSocket countdown timer
- Preview page — fullscreen player + side panel
- Library page — media grid/list with eye-button preview
- Downloads page — trigger download scripts from UI

---

## [v0.0.10 – v0.0.14] — 2026-06-01

### Added
- `download_posts.py` + `download_highlights.py` — fetch IG archive → `organized/`
- `index_content.py` — idempotent upsert from manifests
- `audio_probe.py` — ffprobe music detection
- `orchestrator.py` — stage chainer with retry + notifications
- FastAPI app skeleton (`api/main.py`) — lifespan, CORS, static mounts
- Login page + Supabase auth flow
- GitHub Actions: backend CI → Hetzner (`release.yml`), frontend CI → Vercel (`frontend-release.yml`)
- Dockerfile + `docker-compose.yml`; Caddy snippet + systemd unit

---

## [v0.0.1 – v0.0.9] — 2026-05-31

### Added
- Project scaffolding: monorepo layout (`backend/`, `frontend/`, `assets/`, `deploy/`, `plan/`)
- React + Vite + shadcn/ui frontend base
- `config.py` — env vars + path constants
- Initial pipeline scripts skeleton
- `.env.example`, `.gitignore`, `requirements.txt`
- Initial README and SETUP guide

---

## Version Scheme

| Tag pattern | Target |
|---|---|
| `vX.Y.Z` | Backend (Docker image → Hetzner CX33) |
| `fe-vX.Y.Z` | Frontend (Vercel production) |

Minor bump (`0.X`) = new user-facing feature set.  
Patch bump (`0.0.X`) = fix or incremental addition within a feature set.
