"""video-text-remover (vtr) — vendored inference.

Clean-room, cog-free reimplementation of hjunior29/video-text-remover: a YOLO11s
ONNX text detector (detector.py) + cv2.inpaint removal (inpaint.py), wrapped in
the frozen `remove_text` contract that backend/pipeline/decaption.py depends on.

Weights: loaded from $DECAPTION_WEIGHTS, else DECAPTION_MODELS_DIR/converted_best.onnx,
else the first *.onnx found under DECAPTION_MODELS_DIR. When no weights / onnxruntime
are present, remove_text raises ImportError — decaption.py catches that and passes
the clip through uncleaned (media.decaptioned stays 0), so the app still runs.

Output is VIDEO-ONLY (no audio) — decaption.py re-muxes the original audio after.

Public API (frozen):
    remove_text(src, out, method="hybrid", bbox=None, min_confidence=0.35,
                dilate_px=6, detect_mode="auto", detection_interval=15) -> dict
    → {"found": bool, "regions": int, "out": str | None}
"""

import glob
import logging
import os

log = logging.getLogger(__name__)

__all__ = ["remove_text"]

# Probe this many evenly-spaced frames up front to decide whether the clip has any
# burned-in text at all — the common case (no text) then skips the full re-encode.
_PROBE_SAMPLES = 12


def _resolve_weights() -> str:
    env = os.environ.get("DECAPTION_WEIGHTS")
    if env and os.path.isfile(env):
        return env
    try:
        from backend.config import DECAPTION_MODELS_DIR
        models_dir = str(DECAPTION_MODELS_DIR)
    except Exception:  # pragma: no cover - config always importable in-app
        models_dir = os.environ.get("DECAPTION_MODELS_DIR", "")
    if models_dir:
        default = os.path.join(models_dir, "converted_best.onnx")
        if os.path.isfile(default):
            return default
        found = sorted(glob.glob(os.path.join(models_dir, "*.onnx")))
        if found:
            return found[0]
    raise ImportError(
        "decaption: no ONNX detector weights found — place converted_best.onnx under "
        "DECAPTION_MODELS_DIR (or set $DECAPTION_WEIGHTS); see backend/vendor/vtr/README.md"
    )


def _bbox_to_region(bbox):
    """(x, y, w, h) → (x1, y1, x2, y2), or None."""
    if not bbox:
        return None
    x, y, w, h = bbox
    return (int(x), int(y), int(x) + int(w), int(y) + int(h))


def remove_text(
    src,
    out,
    method="hybrid",
    bbox=None,
    min_confidence=0.35,
    dilate_px=6,
    detect_mode="auto",
    detection_interval=15,
):
    """See module docstring. Raises ImportError when the backend/weights are
    unavailable (→ decaption pass-through); returns the result dict otherwise."""
    # Heavy deps imported lazily so a missing wheel surfaces as ImportError.
    import cv2  # noqa: F401  (onnxruntime/numpy pulled in by detector)

    from .detector import OnnxTextDetector
    from .inpaint import inpaint_frame

    region = _bbox_to_region(bbox)
    fixed_custom = detect_mode == "custom" and region is not None

    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise RuntimeError(f"decaption: cannot open source video {src}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    detector = None
    if not fixed_custom:
        detector = OnnxTextDetector(_resolve_weights(), conf=min_confidence)

        # --- Probe pass: is there any text worth a full re-encode? ---
        found_any = False
        if total > 0:
            step = max(1, total // _PROBE_SAMPLES)
            idx = 0
            while idx < total:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, frame = cap.read()
                if not ok:
                    break
                if detector.detect(frame, region=region):
                    found_any = True
                    break
                idx += step
        else:  # unknown length — scan sequentially up to a cap
            for _ in range(_PROBE_SAMPLES * detection_interval):
                ok, frame = cap.read()
                if not ok:
                    break
                if detector.detect(frame, region=region):
                    found_any = True
                    break

        if not found_any:
            cap.release()
            return {"found": False, "regions": 0, "out": None}

    # --- Process pass: inpaint every frame, redetect every N frames. ---
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out, fourcc, fps, (width, height))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"decaption: cannot open VideoWriter for {out}")

    max_regions = 0
    boxes = []
    if fixed_custom:
        boxes = [list(region)]
        max_regions = 1

    fi = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if not fixed_custom and (fi % max(1, detection_interval) == 0):
                boxes = detector.detect(frame, region=region)
                max_regions = max(max_regions, len(boxes))
            writer.write(inpaint_frame(frame, boxes, method, dilate_px))
            fi += 1
    finally:
        cap.release()
        writer.release()

    return {"found": True, "regions": max_regions, "out": out}
