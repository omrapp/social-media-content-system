"""Deterministic test clips for the merge_clips golden harness.

Generates a small set of 1080x1920 H.264 clips from FFmpeg `lavfi` sources, so
every run of the golden suite sees byte-identical inputs (the cv2 metrics in
`_window_metrics` feed directly into the resolved FFmpeg filter strings, so the
pixels have to be stable or the goldens move).

The set deliberately spans the adaptive branches in merge_clips:

  bright_motion  testsrc2   sharp + high inter-frame motion  -> no slow-mo, no Ken Burns (adaptive)
  detail_slow    mandelbrot sharp + low motion               -> slow-mo + Ken Burns (adaptive)
  static_bars    smptebars  sharp + zero motion              -> slow-mo + Ken Burns (adaptive)
  dark_soft      dark blur  dark + soft                      -> hqdn3d denoise + cas sharpen (adaptive)

  short_a/b/c    ~1.6 s clips, used only by the thin-pool case so the
                 min-duration guarantee in merge_clips.run() fires.

Usage:
    python tests/fixtures/clips/make_clips.py          # generate (skips existing)
    python tests/fixtures/clips/make_clips.py --force  # regenerate
    python tests/fixtures/clips/make_clips.py --probe  # print cv2 metrics per clip

The test suite calls ensure_clips() itself, so you normally never run this by
hand -- but regenerating IS a golden-invalidating change (see
tests/README_merge_golden.md).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CLIPS_DIR = Path(__file__).resolve().parent / "media"
# Stands in for backend.config.MUSIC_DIR during golden runs, so an explicit
# `music_path` override resolves inside the containment check in
# merge_clips._safe_music_path without depending on the user's assets/music/.
MUSIC_DIR = Path(__file__).resolve().parent / "music"
MUSIC_BED = "golden_bed.m4a"

W, H, FPS = 1080, 1920, 30

# name -> (lavfi source graph, duration seconds, extra -vf or None)
_SPECS: dict[str, tuple[str, float, str | None]] = {
    # Sharp, saturated, lots of inter-frame motion.
    "bright_motion": (f"testsrc2=size={W}x{H}:rate={FPS}", 12.0, None),
    # Fine detail, near-static -> low motion_mag.
    "detail_slow": (f"mandelbrot=size={W}x{H}:rate={FPS}", 12.0, None),
    # Hard edges, literally zero motion.
    "static_bars": (f"smptebars=size={W}x{H}:rate={FPS}", 12.0, None),
    # Dark + soft: drives the adaptive denoise (expo < 0.45 and sharp < 0.6)
    # and adaptive cas-sharpen (sharp < 0.5) branches in _segment_cleanup.
    "dark_soft": (
        f"testsrc2=size={W}x{H}:rate={FPS}",
        12.0,
        "boxblur=12:2,eq=brightness=-0.42:contrast=0.55:saturation=0.4",
    ),
    # Thin-pool set: too short to fill a 20 s target, so the min-duration
    # guarantee loops the montage.
    "short_a": (f"testsrc2=size={W}x{H}:rate={FPS}", 1.6, None),
    "short_b": (f"smptebars=size={W}x{H}:rate={FPS}", 1.6, None),
    "short_c": (f"mandelbrot=size={W}x{H}:rate={FPS}", 1.6, None),
}

# Long-form clips (the main pool) vs. the deliberately short thin-pool clips.
MAIN_CLIPS = ["bright_motion", "detail_slow", "static_bars", "dark_soft"]
SHORT_CLIPS = ["short_a", "short_b", "short_c"]


def clip_path(name: str) -> Path:
    return CLIPS_DIR / f"{name}.mp4"


def _render(name: str, spec: tuple[str, float, str | None]) -> Path:
    src, dur, vf = spec
    dest = clip_path(name)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", src,
        # Real source footage always carries an audio stream, and
        # merge.audio_mode="original" muxes the longest cut's own audio. Without
        # a track here that path builds a filtergraph referencing [N:a] and
        # ffmpeg aborts with "Stream specifier ':a' matches no streams".
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", f"{dur:.3f}",
    ]
    if vf:
        cmd += ["-vf", vf]
    cmd += [
        "-c:a", "aac", "-b:a", "96k", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "34",
        "-g", str(FPS), "-pix_fmt", "yuv420p",
        # Strip encoder/date metadata so the files are reproducible.
        "-fflags", "+bitexact", "-flags:v", "+bitexact",
        "-movflags", "+faststart",
        "-y", str(dest),
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"make_clips: ffmpeg failed for {name}: "
            f"{(res.stderr or b'').decode('utf-8', 'replace')[-600:]}"
        )
    return dest


def ensure_clips(force: bool = False) -> dict[str, Path]:
    """Generate any missing fixture clip. Returns {name: path}."""
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for name, spec in _SPECS.items():
        dest = clip_path(name)
        if force or not dest.exists() or dest.stat().st_size == 0:
            _render(name, spec)
        out[name] = dest
    return out


def ensure_music(force: bool = False) -> Path:
    """A short deterministic music bed (dual sine + a beat-ish pulse), used as
    the stand-in track for the explicit-music_path case."""
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    dest = MUSIC_DIR / MUSIC_BED
    if not force and dest.exists() and dest.stat().st_size > 0:
        return dest
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100:duration=20",
        "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=20",
        "-filter_complex", "[0:a][1:a]amix=inputs=2,tremolo=f=2:d=0.7[a]",
        "-map", "[a]", "-c:a", "aac", "-b:a", "128k",
        "-fflags", "+bitexact",
        "-y", str(dest),
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(
            "make_clips: ffmpeg failed for the music bed: "
            + (res.stderr or b"").decode("utf-8", "replace")[-600:]
        )
    return dest


def _probe() -> None:
    """Print the cv2 metrics merge_clips would see, to sanity-check that each
    adaptive branch is actually reachable with this clip set."""
    from backend.pipeline.merge_clips import _cv2mod, _window_metrics, _probe_duration

    cv2 = _cv2mod()
    if cv2 is None:
        print("cv2 unavailable -- adaptive branches will not fire")
        return
    print(f"{'clip':<14} {'dur':>6} {'sharp':>6} {'expo':>6} {'motion':>7} {'mag':>6}  branches")
    for name in _SPECS:
        p = str(clip_path(name))
        d = _probe_duration(p)
        met = _window_metrics(cv2, p, 0.0, min(2.5, max(0.5, d - 0.1)))
        if not met:
            print(f"{name:<14} {d:>6.2f}  <no metrics>")
            continue
        br = []
        if met["motion_mag"] < 0.30:
            br.append("slowmo")
        if met["motion_mag"] < 0.45:
            br.append("kenburns")
        if met["expo"] < 0.45 and met["sharp"] < 0.6:
            br.append("denoise")
        if met["sharp"] < 0.5:
            br.append("cas")
        print(f"{name:<14} {d:>6.2f} {met['sharp']:>6.3f} {met['expo']:>6.3f} "
              f"{met['motion']:>7.3f} {met['motion_mag']:>6.3f}  {','.join(br) or '-'}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    if "--probe" in sys.argv and not force:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        ensure_clips()
        _probe()
    else:
        paths = ensure_clips(force=force)
        paths[MUSIC_BED] = ensure_music(force=force)
        total = sum(p.stat().st_size for p in paths.values())
        for name, p in paths.items():
            print(f"{name:<14} {p.stat().st_size / 1024:>8.1f} KB  {p}")
        print(f"{'total':<14} {total / 1024:>8.1f} KB")
        if "--probe" in sys.argv:
            sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
            _probe()
