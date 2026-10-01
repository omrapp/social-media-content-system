# CLAUDE.md

Guidance for AI coding agents (Claude Code etc.) working in this repo.

- Project overview + setup: [`README.md`](README.md)
- Full technical reference (layout, API, settings keys, scripts, deploy): [`docs/REFERENCE.md`](docs/REFERENCE.md)
- Environment variables: [`.env.example`](.env.example) and [`frontend/.env.example`](frontend/.env.example)

## Conventions
- Content taxonomy is generic: one `category` + freeform `tags`. Don't reintroduce niche-specific fields.
- Secrets live in `.env` only — never in the settings table, code, or `VITE_*` vars.
- Backend writes need `SUPABASE_SERVICE_KEY`; the frontend only ever gets the anon key.
- APScheduler runs in a single uvicorn worker (`--workers 1`); don't add workers.
- New user-tunable behavior goes in Settings (`backend/api/routes/settings.py`) with a sane default, and is documented in `docs/REFERENCE.md` + `RELEASE_NOTES.md`.
- Keep changes scoped; run `pytest` (backend) and `npx tsc --noEmit` in `frontend/` before committing.
