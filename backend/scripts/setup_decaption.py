"""
Set up the decaption backend (video-text-remover).  ── MANUAL, USER-RUN ──

Intentionally NOT called by the pipeline or any agent. It installs the light deps
(no torch/paddle), fetches the YOLO11s detection weights into DECAPTION_MODELS_DIR,
and runs a 1-clip smoke test. The heavy download is gated behind --run; without
it, this script only PRINTS the commands + instructions (keeps multi-hundred-MB
fetches off any automated run).

Usage:
    # 1. See what to install + fetch (no writes, no download):
    python -m backend.scripts.setup_decaption

    # 2. Actually install deps + fetch weights + smoke-test:
    python -m backend.scripts.setup_decaption --run
    python -m backend.scripts.setup_decaption --run --smoke-clip /path/to/clip.mp4

The inference code is ALREADY vendored in backend/vendor/vtr/ (detector + inpaint
+ remove_text). This script only installs deps (prod ships them in the Docker
image via requirements.txt) and helps you place the detector weights. After the
weights are in DECAPTION_MODELS_DIR, enable the feature in Settings → Decaption.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from backend.config import DECAPTION_MODELS_DIR

# Light deps only — ONNX Runtime + OpenCV path (no torch, no paddle).
PIP_PACKAGES = ["onnxruntime", "opencv-python", "numpy", "pillow"]

# YOLO11s detection weights (tens of MB). Replace the URL with the exact asset the
# vendored video-text-remover build expects; kept as a documented placeholder so
# no automated run ever pulls hundreds of MB by surprise.
# The vendored detector loads DECAPTION_MODELS_DIR/converted_best.onnx (or the
# first *.onnx there, or $DECAPTION_WEIGHTS). This is the file shipped inside the
# video-text-remover repo at models/text_detector/converted_best.onnx.
WEIGHTS_URL = "https://github.com/hjunior29/video-text-remover (models/text_detector/converted_best.onnx)"
WEIGHTS_FILE = DECAPTION_MODELS_DIR / "converted_best.onnx"


def _pip_install() -> None:
    cmd = [sys.executable, "-m", "pip", "install", *PIP_PACKAGES]
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _fetch_weights() -> None:
    print(f"Fetch YOLO11s weights → {WEIGHTS_FILE}")
    if WEIGHTS_FILE.exists():
        print(f"  already present ({WEIGHTS_FILE.stat().st_size // 1024} KB) — skipping")
        return
    print("  MANUAL STEP: download the YOLO11s .onnx detection weights that your")
    print(f"  vendored video-text-remover build expects from:\n    {WEIGHTS_URL}")
    print(f"  and place the file at:\n    {WEIGHTS_FILE}")
    print("  (weights are git-ignored — keep them out of the repo).")


def _smoke_test(clip: str | None) -> None:
    if not clip:
        print("Smoke test: pass --smoke-clip /path/to/captioned.mp4 to run a 1-clip check.")
        return
    if not Path(clip).exists():
        print(f"Smoke test: clip not found: {clip}")
        return
    print(f"Smoke test on {clip} …")
    try:
        from backend.vendor.vtr import remove_text
    except ImportError as exc:
        print(f"  video-text-remover not vendored yet ({exc}).")
        print("  Drop the real inference code into backend/vendor/vtr/ (see its README), then re-run.")
        return
    out = DECAPTION_MODELS_DIR / "_smoke_out.mp4"
    res = remove_text(clip, str(out))
    print(f"  result: {res}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up the decaption backend (manual)")
    parser.add_argument("--run", action="store_true",
                        help="Actually install deps + fetch weights (default: just print).")
    parser.add_argument("--smoke-clip", help="Path to a captioned clip for the 1-clip smoke test.")
    args = parser.parse_args()

    print("=== Decaption setup (video-text-remover) ===")
    print(f"Models dir: {DECAPTION_MODELS_DIR}\n")

    if not args.run:
        print("DRY RUN — commands that --run would execute:\n")
        print(f"  $ {sys.executable} -m pip install {' '.join(PIP_PACKAGES)}")
        print(f"  # then place the detector weights → {WEIGHTS_FILE}")
        print(f"  #   (from {WEIGHTS_URL})")
        print("  # inference code is already vendored in backend/vendor/vtr/")
        print("\nRe-run with --run to install deps + check weights.")
        return

    _pip_install()
    _fetch_weights()
    _smoke_test(args.smoke_clip)
    print("\nDone. Once the weights are in place, enable Settings → Decaption.")


if __name__ == "__main__":
    main()
