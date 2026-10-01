import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.db import get_supabase, _use_supabase
from backend.api.auth import verify_token
from backend.api.ws import broadcast, log_broadcast

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"], dependencies=[Depends(verify_token)])

STAGE_MODULES = {
    "download_posts": "backend.pipeline.download_posts",
    "download_highlights": "backend.pipeline.download_highlights",
    "index": "backend.pipeline.index_content",
    "classify": "backend.pipeline.classify_groq",
    "resize": "backend.pipeline.resize_clips",
    "enhance": "backend.pipeline.enhance_video",
    "edit": "backend.pipeline.video_edit",
    "upload": "backend.pipeline.upload_r2",
    "caption": "backend.pipeline.caption_gen",
    "schedule": "backend.pipeline.scheduler",
}

FULL_PIPELINE_ORDER = ["index", "resize", "edit", "upload"]


class PipelineRequest(BaseModel):
    media_id: str | None = None
    category: str | None = None
    tags: list[str] | None = None


def _run_stage(stage: str, params: dict) -> dict:
    if stage not in STAGE_MODULES:
        raise HTTPException(400, f"Unknown stage: {stage}")
    import importlib
    mod = importlib.import_module(STAGE_MODULES[stage])
    kwargs = {}
    if stage == "caption" and params.get("category"):
        kwargs = {k: params[k] for k in ["category", "tags"] if params.get(k)}
    elif params.get("media_id"):
        kwargs["media_id"] = params["media_id"]
    return mod.run(**kwargs)


class OrchestratorRequest(BaseModel):
    stages: list[str] | None = None
    media_id: str | None = None
    include_downloads: bool = False


@router.post("/full")
async def trigger_full(body: PipelineRequest):
    params = body.model_dump(exclude_none=True)
    results = {}
    await log_broadcast("log", "pipeline", "Full pipeline started")
    for stage in FULL_PIPELINE_ORDER:
        await broadcast("pipeline_start", {"stage": stage})
        await log_broadcast("log", "pipeline", f"Stage started: {stage}")
        try:
            result = _run_stage(stage, params)
            results[stage] = result
            await broadcast("pipeline_complete", {"stage": stage, "result": result})
            await log_broadcast("success", "pipeline", f"Stage complete: {stage}", result)
        except Exception as e:
            await log_broadcast("error", "pipeline", f"Stage failed: {stage} — {e}")
            raise
    await log_broadcast("success", "pipeline", "Full pipeline complete", results)
    return {"stages": results}


@router.post("/orchestrate")
async def trigger_orchestrator(body: OrchestratorRequest):
    await broadcast("pipeline_start", {"stage": "orchestrator"})
    await log_broadcast("log", "pipeline", "Orchestrator started", {
        "include_downloads": body.include_downloads,
        "stages": body.stages,
    })
    from backend.pipeline.orchestrator import run as orchestrate
    loop = asyncio.get_running_loop()

    def progress_cb(stage: str, status: str, data: dict):
        event = "pipeline_stage_start" if status == "start" else "pipeline_stage_complete"
        asyncio.run_coroutine_threadsafe(broadcast(event, {"stage": stage, "result": data}), loop)

    try:
        result = await asyncio.to_thread(
            orchestrate,
            stages=body.stages,
            media_id=body.media_id,
            include_downloads=body.include_downloads,
            progress_callback=progress_cb,
        )
        await broadcast("pipeline_complete", {"stage": "orchestrator", "result": result})
        await log_broadcast("success", "pipeline", "Orchestrator complete", result)
        return result
    except Exception as e:
        await log_broadcast("error", "pipeline", f"Orchestrator failed — {e}")
        raise


@router.post("/{stage}")
async def trigger_stage(stage: str, body: PipelineRequest):
    params = body.model_dump(exclude_none=True)
    await broadcast("pipeline_start", {"stage": stage})
    await log_broadcast("log", "pipeline", f"Stage started: {stage}", params or None)
    try:
        result = _run_stage(stage, params)
        await broadcast("pipeline_complete", {"stage": stage, "result": result})
        await log_broadcast("success", "pipeline", f"Stage complete: {stage}", result)
        return {"stage": stage, "result": result}
    except Exception as e:
        await log_broadcast("error", "pipeline", f"Stage failed: {stage} — {e}")
        raise


@router.get("/runs")
def get_runs(limit: int = Query(default=20, le=100)):
    if not _use_supabase():
        return []
    return (
        get_supabase()
        .table("pipeline_runs")
        .select("*")
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )
