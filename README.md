# Social Media Content System

Self-hosted pipeline that turns your own raw video/photo library into edited,
captioned, color-graded short-form reels and publishes them to Instagram,
TikTok, and YouTube on a schedule — with AI-assisted classification,
captioning, clip selection, and an optional Telegram bot for on-the-go
approvals. Open source under the [MIT License](LICENSE).

Content is organized by a flexible **category** (a single content type, e.g.
`food`, `fitness`, `culture` — fully configurable in Settings) plus optional
freeform **tags**. Nothing in the pipeline assumes any particular niche.

## What it does

- Ingests your own video/photo archive (manual upload, URL fetch, Google
  Drive/Photos, or an Instagram archive import) and indexes it into a
  Supabase-backed (or local SQLite) database
- Classifies new clips by category + descriptive tags and scores them with an
  AI "hook" score, using Groq (with a local Ollama fallback)
- Generates bilingual (EN + AR) captions and hashtags via OpenRouter, with
  optional trend-injection and a self-critique refine pass
- Cuts single clips or builds multi-clip cinematic montages (color grading,
  Ken Burns, beat-synced cuts, slow motion, optional B-roll from
  Pexels/Pixabay) with an in-browser non-linear reel editor
- Schedules and auto-publishes to Instagram, TikTok, and YouTube Shorts, with
  approval gates, analytics ingestion, and A/B hashtag testing
- Optional Telegram bot: push previews, approve/reject/reschedule inline, and
  a `/create` wizard to spin up a new reel from your phone

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Your footage: manual upload / URL / Google Drive+Photos /    │
│  Instagram archive import / stock B-roll (Pexels, Pixabay)    │
│  organized/<category>/<id>/                                   │
└───────────────────────────┬────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI Backend  (backend/)                                  │
│  ├── Pipeline: index → classify → resize/merge → edit →       │
│  │             caption → upload → schedule                    │
│  ├── APScheduler daemon (single worker)                       │
│  ├── WebSocket broadcast                                      │
│  └── REST API  /api/*                                         │
└──────┬───────────────────────────────┬────────────────────────┘
       │                               │
       ▼                               ▼
┌──────────────┐              ┌─────────────────────────┐
│  Supabase    │              │  React Frontend          │
│  (Postgres   │              │  (frontend/)             │
│   + Auth     │              │  Create / Queue / Preview│
│   + RLS)     │              │  / Library / Editor /    │
└──────────────┘              │  Analytics / Settings    │
                               └─────────────────────────┘
                                          │
                                          ▼
                               ┌─────────────────────────┐
                               │  Telegram Bot (optional) │
                               │  Preview push, approve/  │
                               │  reject, /create wizard  │
                               └─────────────────────────┘
                                          │
                                          ▼
                      Instagram · TikTok · YouTube Shorts
```

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.12+ | |
| Node.js 20+ | |
| FFmpeg 7.x | plus `libvidstab` for stabilization |
| A Supabase project | Postgres + Auth + RLS backing store |
| A Cloudflare R2 bucket | public bucket the platforms pull video from |
| A Meta Developer app | Instagram Business/Creator account, Graph API access |
| An OpenRouter account | caption generation |
| A Groq account | classification (free tier) |
| A Pixabay account | background music |

Everything else (YouTube, TikTok, Telegram, Google Drive/Photos import, stock
footage, Zernio) is optional and gated behind its own settings toggle — the
app runs fine without any of them configured.

## Quick start

### 1. Backend

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in the required values (see table below)
```

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env   # fill in VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
cd ..
```

### 3. Database

```bash
supabase login
supabase link --project-ref YOUR_PROJECT_REF
supabase db push
```

No Supabase CLI? Run every file in `supabase/migrations/` in order through the
Supabase SQL editor instead. If `SUPABASE_URL`/`SUPABASE_KEY` are left unset,
the backend falls back to a local SQLite file (`content.db`) — fine for
trying things out, not recommended for production.

### 4. Run it

```bash
# Backend — single worker is required, APScheduler doesn't support more
uvicorn backend.api.main:app --reload --workers 1 --port 8000
curl http://localhost:8000/api/health   # {"status":"ok",...}

# Frontend (separate terminal)
cd frontend && npm run dev              # http://localhost:5173
```

In dev, Vite proxies `/api`, `/static`, and `/ws` to `localhost:8000` — leave
`VITE_API_BASE_URL` unset.

### 5. Verify your setup

- `GET /api/health` returns `{"status":"ok"}`
- `GET /api/settings` returns your settings groups + a `secrets_set` map
- The frontend loads at `http://localhost:5173` and the WebSocket connects
  (check the browser console for `ws connected`)
- `python -m backend.pipeline.index_content` runs cleanly against an empty
  library

### Docker (alternative to steps 1–2)

```bash
docker compose up -d api
```

Builds from `Dockerfile` (installs FFmpeg + deps), runs on `127.0.0.1:8000`,
mounts `downloads/`, `db/`, `assets/`, `reels_ready/`, `logs/` from the host.
`docker-compose.yml` also defines an optional `ollama` sidecar for the
nightly local vision-scoring fallback (`vision.provider=local`) — most setups
don't need it; skip with `docker compose up -d api` alone.

## Environment variables

See [`.env.example`](.env.example) for the full annotated list — everything
under "required" must be filled in before the backend will do anything
useful; everything else is opt-in and gated by its own settings toggle.
Frontend variables live in `frontend/.env.example`.

## Pipeline scripts

Every stage can also be run by hand for debugging or backfills:

```bash
python -m backend.pipeline.index_content                 # idempotent, safe to re-run
python -m backend.pipeline.classify_groq                  # category + tags (new downloads only)
python -m backend.pipeline.caption_gen --category food --tags "meal-prep,budget"
python -m backend.pipeline.resize_clips
python -m backend.pipeline.upload_r2
python -m backend.pipeline.orchestrator --stages index,classify,resize,caption,upload
```

Full script/settings reference lives in [`docs/REFERENCE.md`](docs/REFERENCE.md).

## Telegram bot (optional)

```bash
# .env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_MODE=poll   # dev, default — no public URL needed
```

For production, set `TELEGRAM_MODE=webhook` and register it once:

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-domain>/api/telegram/webhook/<TELEGRAM_WEBHOOK_SECRET>"
```

| Command | Description |
|---|---|
| `/queue` | Upcoming scheduled posts |
| `/pending` | Posts awaiting approval |
| `/stats` | Media counts |
| `/settings` | Current settings summary |
| `/create` | Wizard: pick a category → optional tags → confirm → publish |
| `/help` | Command list |

## Maintenance

- **Meta access token expires every 60 days.** Refresh via the Graph API's
  token-refresh endpoint and update `IG_TOKEN`.
- **TikTok access token expires every 24h, refresh token every 365 days.**
  `python -m backend.scripts.refresh_tiktok_token` handles the 24h refresh —
  put it on a cron job.
- **Adding music or color-grade LUTs**: drop files into `assets/music/` or
  `assets/luts/`, they're picked up automatically. The repo ships only three
  basic LUTs (`warm`/`cool`/`vintage`); third-party packs aren't redistributed —
  put your own `.cube` files in `assets/luts/cinematic/` and the curated
  `assets/luts/catalog.json` tags any whose filenames match (LUT preview thumbnails
  need one manual step: `python -m backend.scripts.make_lut_previews`).

## Deployment

`deploy/deploy.sh` / `deploy/rollback.sh` and `deploy/social-media-cms.service` are
a working example systemd + reverse-proxy setup — copy and adapt the
domain/paths for your own host. `.github/workflows/` has example CI that
builds a Docker image on a `vX.Y.Z` tag and deploys the frontend to Vercel on
an `fe-vX.Y.Z` tag; both need the repo secrets listed in
[`docs/REFERENCE.md`](docs/REFERENCE.md#github-secrets-required) configured before they'll
run. Neither is required — `uvicorn` + a static file host work fine for a
single-server setup.

## Key constraints

- Never post the same `media_id` twice — enforced by the scheduler
- Videos must have a public R2 URL before they can be scheduled
- `SUPABASE_SERVICE_KEY` is backend-only — never expose it to the frontend
  (only `VITE_*`-prefixed vars, which use the anon key, are safe to bundle)
- APScheduler requires exactly one uvicorn worker (`--workers 1`)

## Project structure

```
backend/
  config.py            — env vars + path constants
  db.py                — Supabase-first / SQLite-fallback abstraction
  pipeline/             — download, classify, caption, edit, merge, publish, schedule stages
  api/routes/           — media, posts, downloads, taxonomy, analytics, assets,
                           settings, editor, pipeline, telegram
frontend/
  src/pages/            — Create, Library, Queue, Preview, Editor, Analytics,
                           Downloads, Assets, Settings
  src/components/       — pickers, panels, the reel editor's timeline/inspectors
assets/
  music/, luts/, fonts/, stickers/
supabase/migrations/    — schema history, apply in order
deploy/                 — example systemd unit + deploy/rollback scripts
```

Full API reference, settings-key reference, and DB state machine live in
[`docs/REFERENCE.md`](docs/REFERENCE.md).

## License

[MIT](LICENSE).
