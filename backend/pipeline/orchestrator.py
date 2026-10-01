"""
End-to-end pipeline orchestrator.
Chains stages with error handling, retry, and notifications.

Usage:
    python -m backend.pipeline.orchestrator
    python -m backend.pipeline.orchestrator --stages index,resize,edit
    python -m backend.pipeline.orchestrator --media-id abc123
"""

import argparse
import importlib
import logging
import traceback
import time

from backend.db import (
    log_pipeline_run, update_pipeline_run,
    create_notification, get_media, update_status, get_setting,
)
from backend.pipeline.quality_probe import QualityRejected

log = logging.getLogger(__name__)

STAGE_MODULES = {
    "download_posts": "backend.pipeline.download_posts",
    "download_highlights": "backend.pipeline.download_highlights",
    "index": "backend.pipeline.index_content",
    "classify": "backend.pipeline.classify_groq",
    "classify_vision": "backend.pipeline.classify_vision",
    "quality_probe": "backend.pipeline.quality_probe",
    "decaption": "backend.pipeline.decaption",
    "resize": "backend.pipeline.resize_clips",
    "merge": "backend.pipeline.merge_clips",
    "enhance": "backend.pipeline.enhance_video",
    "stock_footage": "backend.pipeline.stock_footage",
    "voiceover": "backend.pipeline.voiceover",
    "edit": "backend.pipeline.video_edit",
    "remotion": "backend.pipeline.remotion_render",
    "upload": "backend.pipeline.upload_r2",
    "caption": "backend.pipeline.caption_gen",
    "caption_refine": "backend.pipeline.caption_gen",
    "schedule": "backend.pipeline.scheduler",
}

# Extra kwargs injected per stage (merged with runtime kwargs like media_id).
STAGE_EXTRA_KWARGS: dict[str, dict] = {
    "caption_refine": {"mode": "refine"},
    "caption": {"mode": "generate"},
}

DEFAULT_PIPELINE = ["index", "resize", "enhance", "edit", "upload"]
FULL_PIPELINE = ["download_posts", "download_highlights", "index", "classify", "classify_vision", "resize", "enhance", "edit", "upload"]

MAX_STAGE_RETRIES = 2


def _run_stage(stage: str, kwargs: dict) -> dict:
    mod = importlib.import_module(STAGE_MODULES[stage])
    merged = {**STAGE_EXTRA_KWARGS.get(stage, {}), **kwargs}
    return mod.run(**merged)


def run(
    stages: list[str] | None = None,
    media_id: str | None = None,
    include_downloads: bool = False,
    auto_schedule: bool = False,
    progress_callback=None,  # Optional[Callable[[str, str, dict], None]]
    feedback: str | None = None,  # forwarded to caption_refine stage only
    lut_override: str | None = None,  # forwarded to the edit stage only (manual LUT pick)
    music_override: str | None = None,  # forwarded to the edit stage only (manual music swap)
    music_start: float | None = None,   # forwarded to the edit stage only (music enter offset)
    keep_original_audio: bool = False,  # edit stage: skip auto music, keep clip audio (manual create)
    no_lut: bool = False,               # edit stage: skip colour grade, keep original video (manual create)
    decaption_force: bool | None = None,  # decaption stage: per-run enable/disable override (None = global)
    voiceover_force: bool | None = None,  # voiceover stage: per-run enable/disable override (None = global)
    edl_overrides: dict | None = None,  # edit stage: reel-editor EditOverrides (LUT/eq/layers/toggles)
):
    if stages is None:
        stages = FULL_PIPELINE if include_downloads else DEFAULT_PIPELINE

    results = {}
    total_processed = 0
    total_failed = 0
    failed_stages = []

    try:
        run_log = log_pipeline_run("orchestrator", metadata={"stages": stages})
    except Exception as exc:
        log.warning("pipeline: log_pipeline_run failed (non-fatal): %s", exc)
        run_log = None
    log.info("pipeline start: stages=%s media_id=%s", stages, media_id or "*")

    try:
        stages_enabled = (get_setting("pipeline", {}) or {}).get("stages_enabled", {})
    except Exception as exc:
        log.warning("pipeline: get_setting failed (non-fatal): %s", exc)
        stages_enabled = {}

    for stage in stages:
        if stage not in STAGE_MODULES:
            log.warning("pipeline: unknown stage '%s' — skipping", stage)
            create_notification("warning", "Unknown stage", f"Skipped unknown stage: {stage}")
            continue

        if stages_enabled.get(stage) is False:
            log.info("pipeline: stage '%s' disabled in settings — skipping", stage)
            results[stage] = {"skipped": True, "reason": "disabled"}
            continue

        kwargs = {}
        if media_id and stage not in ("download_posts", "download_highlights", "index"):
            kwargs["media_id"] = media_id
        # Thread feedback to caption_refine only — other stages don't accept it.
        if feedback and stage == "caption_refine":
            kwargs["feedback"] = feedback
        # Thread a manual LUT pick (Preview edit drawer) to the edit stage only.
        if lut_override and stage == "edit":
            kwargs["lut_override"] = lut_override
        # Thread a manual music swap (Preview edit drawer) to the edit stage only.
        if music_override and stage == "edit":
            kwargs["music_override"] = music_override
            if music_start is not None:
                kwargs["music_start"] = music_start
        # Manual create wizard: keep-original overrides for the edit stage only.
        if stage == "edit":
            if keep_original_audio:
                kwargs["keep_original_audio"] = True
            if no_lut:
                kwargs["no_lut"] = True
            # Reel-editor export: the compiled EditOverrides (LUT, eq, overlay
            # layers, branding/voiceover/intro/cast toggles).
            if edl_overrides is not None:
                kwargs["edl_overrides"] = edl_overrides
        # Per-run decaption enable/disable override for the decaption stage only.
        if decaption_force is not None and stage == "decaption":
            kwargs["decaption_force"] = decaption_force
        # Per-run voiceover enable/disable override for the voiceover stage only.
        if voiceover_force is not None and stage == "voiceover":
            kwargs["voiceover_force"] = voiceover_force

        success = False
        last_error = None

        if progress_callback:
            try:
                progress_callback(stage, "start", {})
            except Exception:
                pass

        for attempt in range(MAX_STAGE_RETRIES + 1):
            try:
                log.info("stage '%s' start (attempt %d/%d) kwargs=%s",
                         stage, attempt + 1, MAX_STAGE_RETRIES + 1, kwargs)
                result = _run_stage(stage, kwargs)
                results[stage] = result

                # Stages may signal a problem without raising (e.g. R2 not configured).
                if isinstance(result, dict) and result.get("error"):
                    log.warning("stage '%s' returned error: %s", stage, result["error"])

                processed = result.get("processed", 0) or result.get("uploaded", 0) or result.get("edited", 0) or result.get("downloaded", 0) or result.get("posts", 0) or 0
                failed = result.get("failed", 0) or result.get("errors", 0) or 0
                total_processed += processed
                total_failed += failed

                log.info("stage '%s' ok: processed=%d failed=%d result=%s",
                         stage, processed, failed, result)

                if failed > 0:
                    log.warning("stage '%s' partial failure: %d ok, %d failed",
                                stage, processed, failed)
                    create_notification(
                        "warning",
                        f"{stage}: partial failure",
                        f"{processed} ok, {failed} failed",
                    )

                if progress_callback:
                    try:
                        progress_callback(stage, "complete", result if isinstance(result, dict) else {})
                    except Exception:
                        pass

                success = True
                break

            except Exception as e:
                # QualityRejected is non-retriable — clip flagged do_not_use, abort immediately.
                if isinstance(e, QualityRejected):
                    last_error = str(e)
                    log.warning("stage '%s' quality-rejected — aborting pipeline (no retry): %s", stage, e)
                    break
                last_error = str(e)
                log.error("stage '%s' attempt %d/%d raised: %s\n%s",
                          stage, attempt + 1, MAX_STAGE_RETRIES + 1,
                          last_error, traceback.format_exc())
                if attempt < MAX_STAGE_RETRIES:
                    backoff = 2 ** attempt
                    log.info("stage '%s' retrying in %ds", stage, backoff)
                    time.sleep(backoff)
                    continue

        if not success:
            results[stage] = {"error": last_error}
            failed_stages.append(stage)
            total_failed += 1

            log.error("stage '%s' FAILED after %d attempts — aborting pipeline. last_error=%s",
                      stage, MAX_STAGE_RETRIES + 1, last_error)
            try:
                create_notification(
                    "error",
                    f"Pipeline stage failed: {stage}",
                    f"After {MAX_STAGE_RETRIES + 1} attempts: {last_error}",
                )
            except Exception as exc:
                log.warning("pipeline: create_notification failed (non-fatal): %s", exc)

            try:
                error_media = get_media(filters={"status": "error"})
                for m in error_media:
                    if m.get("error_message") and last_error and last_error in m["error_message"]:
                        continue
            except Exception as exc:
                log.warning("pipeline: get_media failed (non-fatal): %s", exc)

            break

    status = "completed" if not failed_stages else "failed"
    log.info("pipeline %s: processed=%d failed=%d failed_stages=%s",
             status, total_processed, total_failed, failed_stages or "none")

    if run_log:
        try:
            update_pipeline_run(run_log["id"], {
                "status": status,
                "items_processed": total_processed,
                "items_failed": total_failed,
                "metadata": {"results": {k: str(v) for k, v in results.items()}},
                "completed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            })
        except Exception as exc:
            log.warning("pipeline: update_pipeline_run failed (non-fatal): %s", exc)

    try:
        if status == "completed":
            create_notification(
                "success",
                "Pipeline complete",
                f"Processed {total_processed} items across {len(stages)} stages",
            )
        else:
            create_notification(
                "error",
                "Pipeline stopped",
                f"Failed at: {', '.join(failed_stages)}. {total_processed} items processed before failure.",
            )
    except Exception as exc:
        log.warning("pipeline: create_notification failed (non-fatal): %s", exc)

    return {
        "status": status,
        "stages": results,
        "processed": total_processed,
        "failed": total_failed,
        "failed_stages": failed_stages,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stages", help="Comma-separated stages to run")
    parser.add_argument("--media-id", help="Process single media item")
    parser.add_argument("--include-downloads", action="store_true")
    args = parser.parse_args()

    stage_list = args.stages.split(",") if args.stages else None
    result = run(stages=stage_list, media_id=args.media_id, include_downloads=args.include_downloads)
    print(f"Pipeline {result['status']}: {result['processed']} processed, {result['failed']} failed")
    if result["failed_stages"]:
        print(f"Failed stages: {', '.join(result['failed_stages'])}")
