import os
import re
import uuid
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

_log = logging.getLogger(__name__)

# Explicit allowed origins — CORS_ORIGINS (comma-separated) pins your frontend
# domain(s); VERCEL_FRONTEND_URL pins the production Vercel URL.
_VERCEL_FRONTEND = os.environ.get("VERCEL_FRONTEND_URL", "")
_EXTRA_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
_CORS_ORIGINS = {
    "http://localhost:5173",
    "http://localhost:3000",
    *_EXTRA_ORIGINS,
    *([_VERCEL_FRONTEND] if _VERCEL_FRONTEND else []),
}
# Regex covers PR preview deployments from this specific project prefix.
# If VERCEL_FRONTEND_URL is set, tighten to that project slug; otherwise
# fall back to a broad *.vercel.app pattern (acceptable for preview-only use).
_VERCEL_PROJECT_SLUG = os.environ.get("VERCEL_PROJECT_SLUG", "")
_VERCEL_RE = re.compile(
    rf"https://{re.escape(_VERCEL_PROJECT_SLUG)}-.*\.vercel\.app"
    if _VERCEL_PROJECT_SLUG
    else r"https://.*\.vercel\.app"
)

from backend.config import ORGANIZED_DIR, THUMBS_DIR, TELEGRAM_MODE, TELEGRAM_BOT_TOKEN
from backend.db import init_db
from backend.api.ws import pipeline_ws
from backend.api.routes import media, posts, pipeline, analytics, captions, downloads, notifications, settings
from backend.api.routes.scheduler import router as scheduler_router
from backend.api.routes.statistics import router as statistics_router
from backend.api.routes.classification import router as classification_router
from backend.api.routes.assets import router as assets_router
from backend.api.routes.audio import router as audio_router
from backend.api.routes.edit import router as edit_router
from backend.api.routes.editor import router as editor_router, public_router as editor_public_router
from backend.api.routes.taxonomy import router as taxonomy_router
from backend.api.routes.telegram import router as telegram_router
from backend.api.routes.settings import seed_defaults
from backend.pipeline import daemon


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_defaults()
    daemon.start()

    # Start Telegram long-poll thread in dev; webhook handles prod.
    if TELEGRAM_BOT_TOKEN and TELEGRAM_MODE == "poll":
        from backend.pipeline.telegram_bot import start_poll_thread
        start_poll_thread()

    yield
    daemon.stop()


app = FastAPI(title="Travel Content System", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_CORS_ORIGINS),
    allow_origin_regex=_VERCEL_RE.pattern,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

@app.exception_handler(Exception)
async def _global_exc_handler(request: Request, exc: Exception):
    error_id = uuid.uuid4().hex[:8]
    _log.exception("Unhandled %s %s [error_id=%s]", request.method, request.url.path, error_id)
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in _CORS_ORIGINS or _VERCEL_RE.match(origin):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_id": error_id},
        headers=headers,
    )


app.include_router(media.router)
app.include_router(posts.router)
app.include_router(pipeline.router)
app.include_router(analytics.router)
app.include_router(captions.router)
app.include_router(downloads.router)
app.include_router(notifications.router)
app.include_router(settings.router)
app.include_router(assets_router)
app.include_router(audio_router)
app.include_router(edit_router)
app.include_router(editor_router)
# Signed proxy stream only — no verify_token (a <video> tag can't send a header).
# EDITOR_DIR is never exposed via StaticFiles; this route is the only way in.
app.include_router(editor_public_router)
app.include_router(taxonomy_router)
app.include_router(statistics_router)
app.include_router(classification_router)
app.include_router(telegram_router)
app.include_router(scheduler_router)

app.websocket("/ws/pipeline")(pipeline_ws)

# Serve local media + assets in dev. Prod normally relies on R2 signed URLs, but the
# indexed IG archive has no r2_url, so opt in with SERVE_LOCAL_MEDIA=true to expose it.
_serve_local = (
    os.environ.get("ENV", "dev") != "prod"
    or os.environ.get("SERVE_LOCAL_MEDIA", "").lower() in ("1", "true", "yes")
)
if _serve_local:
    if ORGANIZED_DIR.exists():
        app.mount("/static/media", StaticFiles(directory=str(ORGANIZED_DIR)), name="static_media")
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static/thumbs", StaticFiles(directory=str(THUMBS_DIR)), name="static_thumbs")

# assets/ (music, LUTs, fonts, intro/outro) is indexed into Supabase (assets
# table + a public Storage bucket, v1.10.0) which now provides a public-URL
# fallback for admin-facing consumers (the Assets page, API responses) — but
# the FFmpeg pipeline still reads these files from local disk directly, so
# this mount stays unconditional (outside the SERVE_LOCAL_MEDIA opt-in gate
# above) as the fast local-serve path.
_assets_dir = ORGANIZED_DIR.parent.parent / "assets"
if _assets_dir.exists():
    app.mount("/static/assets", StaticFiles(directory=str(_assets_dir)), name="static_assets")


@app.get("/api/health")
def health():
    from backend.pipeline.daemon import _scheduler
    scheduler_ok = _scheduler is not None and _scheduler.running
    return {
        "status": "ok",
        "scheduler": scheduler_ok,
        "telegram": TELEGRAM_MODE if TELEGRAM_BOT_TOKEN else "disabled",
    }


@app.get("/api/version")
def version_info():
    commit = os.environ.get("GIT_COMMIT", "unknown")
    if len(commit) == 40:
        commit = commit[:7]
    return {
        "backend": {
            "commit":     commit,
            "branch":     os.environ.get("GIT_BRANCH", "unknown"),
            "tag":        os.environ.get("GIT_TAG", "unknown"),
            "build_time": os.environ.get("BUILD_TIME", "unknown"),
        },
    }
