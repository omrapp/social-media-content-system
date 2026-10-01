# vtr — video-text-remover (vendored inference)

The real inference is **vendored** here now (no longer a stub):
`detector.py` (ONNX YOLO11 text detection) + `inpaint.py` (cv2 TELEA/NS/hybrid)
+ `__init__.py` (`remove_text` contract). Clean-room, cog-free reimplementation
of hjunior29/video-text-remover — deps are `onnxruntime` + `opencv` + `numpy`
(shipped in the Docker image via `requirements.txt`). All that's left to provide
is the **detector weights** (kept out of git).

## Source

**https://github.com/hjunior29/video-text-remover** (MIT).

- Approach: **YOLO11** text-region detection + **OpenCV inpaint** (hybrid /
  TELEA / Navier-Stokes) on **ONNX Runtime + OpenCV**. No torch, no paddle, no
  multi-GB weights (YOLO11s ≈ tens of MB). CPU-native (~2–5 FPS on the VPS).
- Does **not** preserve audio — `backend/pipeline/decaption.py` re-muxes the
  original audio track back with ffmpeg after inpaint.

## Weights

The detector loads (in order): `$DECAPTION_WEIGHTS` → `DECAPTION_MODELS_DIR/
converted_best.onnx` → first `*.onnx` under `DECAPTION_MODELS_DIR`. Place the
`converted_best.onnx` shipped in the upstream repo
(`models/text_detector/converted_best.onnx`) at
`<DATA_DIR>/models/converted_best.onnx` (the mounted volume, persists across
redeploys). Missing weights → `remove_text` raises `ImportError` → decaption
passes clips through uncleaned.

## Install (run the helper)

```bash
python -m backend.scripts.setup_decaption          # prints the exact commands
python -m backend.scripts.setup_decaption --run     # actually install + fetch weights
```

That helper: `pip install onnxruntime opencv-python numpy pillow`, fetches the
YOLO11s detection weights into `DECAPTION_MODELS_DIR` (`<DATA_DIR>/models/`, i.e.
the bind-mounted `/srv/social-media-cms/data/models/` in prod — persists across
redeploys), and runs a 1-clip smoke test. In prod these deps ship in the Docker
image via `requirements.txt`; this pip line is for local/dev only.

## Contract to preserve

Expose a module-level `remove_text(src, out, method="hybrid", bbox=None,
min_confidence=0.35, dilate_px=6, detect_mode="auto") -> dict` returning
`{"found": bool, "regions": int, "out": str | None}`. `decaption.py` imports it
guarded — if this raises `ImportError`, the stage passes clips through untouched.

Do **not** commit model weights to git; keep them under `DECAPTION_MODELS_DIR`
(`<DATA_DIR>/models/`, the mounted data volume) on the server.
