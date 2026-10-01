"""
FFmpeg-based video editor with builder pattern.
Applies text overlays, transitions, music, Ken Burns, and LUT color grading.

Usage:
    python -m backend.pipeline.video_edit
    python -m backend.pipeline.video_edit --media-id abc123
"""

import argparse
import json
import logging
import re
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)

from backend.config import LUTS_DIR, ASSETS_DIR, FONTS_DIR, REELS_READY_DIR
from backend.db import get_media, get_media_by_id, update_status, update_media, log_pipeline_run, update_pipeline_run, get_setting

TEMPLATES_DIR = ASSETS_DIR / "templates"

_RENDER_SEM = threading.Semaphore(2)   # allow 2 concurrent encodes per stage


def _num(v, default: float) -> float:
    """Coerce an EDL-supplied number, falling back on anything unusable. Only a
    missing/None value takes the default — 0.0 is a legitimate setting."""
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _media_duration(path: str) -> float | None:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except (ValueError, AttributeError):
        return None


def _segment_mean_db(path: str, start: float, dur: float) -> float | None:
    """Mean loudness (dB) of a [start, start+dur] slice via volumedetect."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}",
         "-t", f"{dur:.3f}", "-i", path, "-map", "0:a:0",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", r.stderr or "")
    return float(m.group(1)) if m else None


def best_audio_offset(audio_path: str, segment_len: float) -> float:
    """Return start (s) of the most energetic `segment_len` window via one ebur128 pass.

    Long Jamendo tracks (2–3 min) usually open with a quiet intro; reels are
    ~15–30s. Picking the most energetic window (chorus/drop) yields a better
    background bed than always cutting from 0:00. C6: replaces the old
    multi-probe volumedetect loop (up to 10 subprocess spawns) with a single
    ebur128 pass that reads all moment-loudness values at once.
    """
    total = _media_duration(audio_path)
    if not total or total <= segment_len + 1:
        return 0.0
    latest = total - segment_len

    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", audio_path,
         "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True, timeout=60,
    )
    # Parse "t: 1.000 M: -14.7 ..." lines (moment loudness, ~1 per second)
    measurements: list[tuple[float, float]] = []
    for line in (r.stderr or "").splitlines():
        m = re.search(r"t:\s*([\d.]+)\s+M:\s*([-\d.inf]+)", line)
        if not m:
            continue
        try:
            t, loudness = float(m.group(1)), float(m.group(2))
        except ValueError:
            continue
        if t <= latest + segment_len:
            measurements.append((t, loudness))

    if not measurements:
        return 0.0

    # Sliding window: find start with highest mean moment loudness.
    step = (measurements[1][0] - measurements[0][0]) if len(measurements) > 1 else 1.0
    win = max(1, round(segment_len / max(step, 0.001)))
    best_start, best_score = 0.0, None
    n = len(measurements)
    for i in range(n - win + 1):
        t = measurements[i][0]
        if t > latest:
            break
        score = sum(measurements[i + j][1] for j in range(win)) / win
        if best_score is None or score > best_score:
            best_score, best_start = score, t

    return max(0.0, min(best_start, latest))

# hqdn3d strength presets for apply_denoise (luma_sp:chroma_sp:luma_tmp:chroma_tmp).
_DENOISE_PRESETS = {
    "light":  "hqdn3d=1.5:1.5:6:6",
    "medium": "hqdn3d=3:3:9:9",
    "strong": "hqdn3d=5:5:12:12",
}

def valid_cube(path) -> bool:
    """True only when *path* is a structurally complete Hald/.cube 3D LUT.

    Guards against the FFmpeg `lut3d ... Unexpected EOF` crash: a .cube file
    declares `LUT_3D_SIZE N` and must then contain exactly N**3 RGB-triplet data
    rows. Truncated or stub files (header present, data missing) parse fine up to
    the EOF, so ffmpeg aborts mid-filter-graph and the whole render fails. We
    pre-count the data rows and reject anything that doesn't match, so the caller
    can skip the grade and still produce a (un-graded) reel instead of erroring.
    """
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            return False
        size = None
        data_rows = 0
        for raw in p.read_text(errors="replace").splitlines():
            s = raw.strip()
            if not s or s.startswith("#") or s.startswith("//"):
                continue
            up = s.upper()
            if up.startswith("LUT_3D_SIZE"):
                try:
                    size = int(s.split()[-1])
                except (ValueError, IndexError):
                    return False
                continue
            if up.startswith("LUT_1D_SIZE") or up.startswith("TITLE") or up.startswith("DOMAIN_"):
                continue
            parts = s.split()
            if len(parts) == 3:
                try:
                    [float(x) for x in parts]
                    data_rows += 1
                except ValueError:
                    pass
        if not size or size < 2:
            return False
        return data_rows == size ** 3
    except Exception:
        return False


def _escape_filter_value(text: str) -> str:
    """Escape a string for use inside a single-quoted ffmpeg filter option value
    (drawtext text, subtitles filename, force_style values, ...). Order matters:
    backslash first (so we don't re-escape our own additions), then % (starts
    %{...} expansion), colon (filter option separator), quote."""
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


# ASS/libass subtitle alignment (numpad-style): 2 = bottom-center, 8 = top-center.
_ASS_ALIGNMENT = {"bottom": 2, "top": 8}


def _ass_color(hex_color: str) -> str:
    """'#RRGGBB' -> ASS PrimaryColour '&H00BBGGRR&'. ASS colour order is BGR, the
    reverse of CSS RGB — not a typo; getting this backwards is the classic ffmpeg
    subtitle-styling bug (colours render swapped, e.g. blue text instead of red)."""
    h = (hex_color or "#ffffff").lstrip("#")
    if len(h) != 6:
        h = "ffffff"
    rr, gg, bb = h[0:2], h[2:4], h[4:6]
    return f"&H00{bb}{gg}{rr}&"


def _subtitle_filter(srt_path: str, cfg: dict) -> str:
    """ffmpeg `subtitles=` filter burning the voiceover SRT, styled from the
    `voiceover` settings group."""
    align = _ASS_ALIGNMENT.get(cfg.get("subtitle_position", "bottom"), 2)
    size = int(cfg.get("subtitle_font_size", 28))
    color = _ass_color(cfg.get("subtitle_color", "#ffffff"))
    escaped_path = _escape_filter_value(str(srt_path))
    style = f"Alignment={align},Fontsize={size},PrimaryColour={color},BorderStyle=1,Outline=1,Shadow=0"
    return f"subtitles='{escaped_path}':force_style='{style}'"


CATEGORY_LUT = {
    "hidden_gem": "warm.cube",
    "budget": "cool.cube",
    "culture": "vintage.cube",
    "nature": "warm.cube",
    "food": "vintage.cube",
    "beach": "cool.cube",
}

# Per-category motion + type profile (Enhancement H). The flat CATEGORY_LUT
# above still drives colour; this adds pacing so each category reads
# differently: energetic categories (budget/food) push a stronger Ken Burns
# zoom, contemplative ones (culture/nature) stay slow.
CATEGORY_PROFILE = {
    "hidden_gem": {"zoom_end": 1.25, "hook_font": 64},
    "budget":     {"zoom_end": 1.35, "hook_font": 64},
    "culture":    {"zoom_end": 1.15, "hook_font": 60},
    "nature":     {"zoom_end": 1.12, "hook_font": 60},
    "food":       {"zoom_end": 1.30, "hook_font": 64},
    "beach":      {"zoom_end": 1.20, "hook_font": 64},
}
_DEFAULT_PROFILE = {"zoom_end": 1.3, "hook_font": 64}


def _hook_overlay(item: dict) -> str:
    """First line of the IG caption, trimmed — the on-screen hook (Enhancement F).
    Falls back to the original IG caption so manual re-edits on a raw clip (no
    generated caption yet) still get a hook line instead of a blank overlay."""
    cap = item.get("caption_ig") or item.get("caption") or item.get("original_caption") or ""
    for line in cap.splitlines():
        line = line.strip()
        if line:
            return line[:42]
    return ""


def _episode_marker(item: dict) -> str:
    """Series progress badge from media metadata, e.g. 'Day 3 of 8 in nature,
    hidden_gem' (Enhancement F). Empty when the clip is not part of a numbered
    series."""
    ep = item.get("episode_number")
    total = item.get("episode_total")
    tags = item.get("tags")
    label = ", ".join(tags) if isinstance(tags, list) and tags else ""
    if ep and total and label:
        return f"Day {ep} of {total} in {label}"
    if ep and label:
        return f"{label} · Episode {ep}"
    if ep and total:
        return f"Day {ep} of {total}"
    if ep:
        return f"Episode {ep}"
    return ""


class VideoEditor:
    def __init__(self, input_path: str):
        self.input_path = input_path
        self.filters: list[str] = []
        self.audio_inputs: list[str] = []
        self.audio_filters: list[str] = []
        self.replace_audio = False
        self.metadata: dict = {}
        # Voiceover (1.8.0): separate from audio_inputs/replace_audio since it
        # mixes in as a final step on top of whatever music/original bed those
        # already describe — see add_voiceover + _build_cmd.
        self.voiceover_path: str | None = None
        self.voiceover_duck_volume: float = 0.08
        # Editor image/sticker overlays (2.0.0 Phase 5). Each one becomes an
        # extra ffmpeg input, appended AFTER every audio input and after the
        # voiceover — _build_cmd hardcodes the music bed as [1:a] and derives
        # voiceover_idx from len(audio_inputs), so an image input anywhere but
        # last would silently re-point those and corrupt the audio of every reel.
        self.image_overlays: list[dict] = []

    def add_text_overlay(self, text: str, position="center", font_size=64, duration=2, start=0):
        x_map = {"center": "(w-text_w)/2", "left": "50", "right": "w-text_w-50"}
        y_map = {"center": "(h-text_h)/2", "top": "100", "bottom": "h-text_h-100"}

        if position in x_map:
            x, y = x_map[position], y_map[position]
        else:
            x, y = x_map["center"], y_map["center"]

        escaped = _escape_filter_value(text)
        self.filters.append(
            f"drawtext=text='{escaped}':fontsize={font_size}:fontcolor=white:"
            f"x={x}:y={y}:enable='between(t,{start},{start + duration})':"
            f"shadowcolor=black:shadowx=2:shadowy=2"
        )
        return self

    def apply_ken_burns(self, zoom_start=1.0, zoom_end=1.3, duration=None):
        zoom_start = max(1.0, min(float(zoom_start), 2.0))
        zoom_end = max(1.0, min(float(zoom_end), 2.0))
        total_frames = max(1, int((float(duration) if duration else 15) * 30))
        self.filters.append(
            f"zoompan=z='if(eq(on,1),{zoom_start:.4f},{zoom_start:.4f}+(({zoom_end:.4f}-{zoom_start:.4f})/{total_frames})*on)':"
            f"d=1:s=1080x1920:fps=30"
        )
        return self

    def apply_lut(self, lut_file: str):
        lut_path = LUTS_DIR / lut_file
        if not lut_path.exists():
            log.warning("apply_lut: %s not found — skipping colour grade", lut_path)
            return self
        if not valid_cube(lut_path):
            # Truncated / stub .cube would crash ffmpeg with "Unexpected EOF" and
            # take the whole render down. Skip the grade instead (un-graded reel
            # still publishes). Fix: replace the file with a complete LUT.
            log.warning("apply_lut: %s is not a complete 3D LUT — skipping colour grade", lut_path)
            return self
        self.filters.append(f"lut3d='{lut_path}'")
        return self

    def apply_denoise(self, strength: str = "light"):
        """Light spatial+temporal denoise via hqdn3d. Run BEFORE motion/scale so
        a zoom doesn't amplify grain. Free, CPU-only — cleans up low-light /
        compressed archive footage (Track 1 video-quality, Enh K)."""
        self.filters.append(_DENOISE_PRESETS.get(strength, _DENOISE_PRESETS["light"]))
        return self

    def apply_sharpen(self, amount: float = 0.4):
        """Contrast-adaptive sharpen (cas) — cheap, halo-free, applied AFTER the
        LUT so the colour grade isn't over-crisped. amount clamped 0..1."""
        amt = max(0.0, min(float(amount), 1.0))
        self.filters.append(f"cas=strength={amt:.2f}")
        return self

    def apply_smooth(self, fps: int = 60):
        """Motion-compensated frame interpolation (minterpolate). CPU-EXPENSIVE —
        opt-in only; smooths slow-mo / panning footage to a higher frame rate."""
        self.filters.append(f"minterpolate=fps={int(fps)}:mi_mode=mci:mc_mode=aobmc")
        return self

    def add_background_music(self, audio_path: str, volume=0.15, fade_out=2, replace=False,
                             start_offset: float | None = None):
        """Add a music track. When replace=True the original clip audio is
        discarded and music becomes the sole audio (used for silent / noisy /
        talking clips). Otherwise music is mixed under the original.

        start_offset (s): explicit enter point into the track. None → the most
        energetic window is auto-detected (best_audio_offset)."""
        self.audio_inputs.append(audio_path)
        self.audio_filters.append(f"volume={volume}")
        self.replace_audio = replace
        self.metadata["fade_out"] = fade_out
        self.metadata["audio_start_offset"] = start_offset
        return self

    def add_voiceover(self, voiceover_path: str, duck_volume: float = 0.08):
        """TTS narration as the reel's primary spoken track. Mixed in as a final
        step in _build_cmd, layered on top of whatever bed (music, mixed
        original+music, or just original) is already queued — kept separate from
        add_background_music so that method's existing mixing logic is untouched."""
        self.voiceover_path = voiceover_path
        self.voiceover_duck_volume = duck_volume
        return self

    def add_image_overlay(self, path: str, x: float = 0.5, y: float = 0.5,
                          w: float | None = None, h: float | None = None,
                          opacity: float = 1.0, start_s: float = 0.0,
                          end_s: float = 0.0):
        """Queue a PNG/WebP sticker composited over the reel. Geometry stays
        NORMALIZED 0–1 here and is resolved into overlay expressions by
        editor_layers.build_image_filters at _build_cmd time, once the input
        index is known. end_s <= start_s means "hold to the end of the reel"."""
        self.image_overlays.append({
            "path": path, "x": x, "y": y, "w": w, "h": h,
            "opacity": opacity, "start_s": start_s, "end_s": end_s,
        })
        return self

    def add_location_text(self, tags: list[str], duration=3, start=2):
        location = ", ".join(tags)
        self.add_text_overlay(location, position="bottom", font_size=48, duration=duration, start=start)
        return self

    def _build_cmd(self, output_path: str, crf: int, preset: str) -> list[str]:
        cmd = ["ffmpeg", "-hide_banner", "-i", self.input_path]

        seg_len = self._get_duration() or 15.0
        manual_offset = self.metadata.get("audio_start_offset")
        for audio in self.audio_inputs:
            # Honor an explicit user-picked enter point; else auto-detect the
            # most energetic window (drop/chorus) instead of the quiet intro.
            offset = float(manual_offset) if manual_offset is not None else best_audio_offset(audio, seg_len)
            cmd.extend(["-stream_loop", "-1"])
            if offset > 0:
                cmd.extend(["-ss", f"{offset:.3f}"])
            cmd.extend(["-i", audio])

        # Voiceover is always the LAST ffmpeg input (after any music input) and
        # mixed in as a separate final step below, so the music/original mixing
        # logic right below (unchanged) can keep writing to its normal label.
        voiceover_idx = None
        if self.voiceover_path:
            voiceover_idx = 1 + len(self.audio_inputs)
            cmd.extend(["-i", self.voiceover_path])

        # Editor stickers are the LAST inputs of all. `[1:a]` below and
        # voiceover_idx above are positional, so anything inserted before this
        # point re-points the audio graph — see plan risk #6.
        image_start_idx = 1 + len(self.audio_inputs) + (1 if self.voiceover_path else 0)
        for ov in self.image_overlays:
            cmd.extend(["-i", ov["path"]])

        has_audio_out = bool(self.audio_inputs) or voiceover_idx is not None
        has_images = bool(self.image_overlays)

        filter_complex = []
        video_label = "0:v"

        if self.filters:
            vf = ",".join(self.filters)
            if has_images:
                # overlay needs a second input, which -vf cannot express, so
                # with stickers the video chain always moves into
                # filter_complex — audio graph or not.
                filter_complex.append(f"[0:v]{vf}[evfx]")
                video_label = "[evfx]"
            elif has_audio_out:
                filter_complex.append(f"[0:v]{vf}[vout]")
                video_label = "[vout]"
            else:
                cmd.extend(["-vf", vf])

        if has_images:
            from backend.pipeline import editor_layers
            frags, video_label = editor_layers.build_image_filters(
                self.image_overlays, image_start_idx,
                # The chain needs a bracketed label; `0:v` (no filters queued)
                # is only bracket-free because -map wants it that way.
                video_label if video_label.startswith("[") else f"[{video_label}]",
            )
            filter_complex.extend(frags)

        bed_label = None
        if self.audio_inputs:
            fade_out = self.metadata.get("fade_out", 2)
            audio_filter = ";".join(self.audio_filters) if self.audio_filters else "volume=0.15"
            probe = self._get_duration()
            fade = f",afade=t=out:st={max(0, probe - fade_out)}:d={fade_out}" if probe else ""
            bed_label = "abed" if voiceover_idx is not None else "aout"
            if self.replace_audio:
                filter_complex.append(f"[1:a]{audio_filter}{fade},apad[{bed_label}]")
            else:
                filter_complex.append(
                    f"[1:a]{audio_filter}{fade}[amusic];"
                    f"[0:a][amusic]amix=inputs=2:duration=first[{bed_label}]"
                )

        if voiceover_idx is not None:
            if bed_label is None:
                # No music queued — duck the clip's own original audio under the
                # narration instead of dropping it entirely.
                filter_complex.append(f"[0:a]volume={self.voiceover_duck_volume}[abed]")
                bed_label = "abed"
            # Flat volume duck, not sidechain compression: this repo's filtergraphs
            # are single-pass with no lookahead/detector chain, so a fixed lower bed
            # volume is an intentional, good-enough MVP simplification.
            filter_complex.append(f"[{bed_label}][{voiceover_idx}:a]amix=inputs=2:duration=first[aout]")

        if filter_complex:
            cmd.extend(["-filter_complex", ";".join(filter_complex)])
            if has_audio_out:
                cmd.extend(["-map", video_label, "-map", "[aout]"])
                if self.replace_audio or voiceover_idx is not None:
                    cmd.append("-shortest")
            elif has_images:
                # Stickers but no audio graph: a filter_complex output is never
                # picked up by ffmpeg's default stream selection, so without an
                # explicit -map the render dies with "Output with label ...
                # does not exist" — and the source audio would be dropped on
                # the floor even if it survived. `0:a?` keeps a silent source
                # (no audio stream at all) from turning that map into an error.
                cmd.extend(["-map", video_label, "-map", "0:a?"])

        cmd.extend([
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-y", output_path,
        ])
        return cmd

    def render(self, output_path: str, crf=22, preset="fast") -> bool:
        with _RENDER_SEM:
            result = subprocess.run(self._build_cmd(output_path, crf, preset), capture_output=True)
        if result.returncode == 0:
            return True

        log.error("ffmpeg render failed (rc=%d):\n%s",
                  result.returncode,
                  result.stderr.decode(errors="replace")[-3000:])

        # Progressive fallback: drop optional/cosmetic filters one tier at a time
        # and retry, so a single bad filter (broken Ken Burns or a corrupt LUT)
        # degrades the reel instead of failing the whole edit. Order = least to
        # most visually important.
        for token, label in (("zoompan", "ken-burns"), ("lut3d", "colour grade")):
            if any(token in f for f in self.filters):
                log.warning("render: retrying without %s (%s stripped)", label, token)
                self.filters = [f for f in self.filters if token not in f]
                with _RENDER_SEM:
                    result = subprocess.run(self._build_cmd(output_path, crf, preset), capture_output=True)
                if result.returncode == 0:
                    return True
                log.error("ffmpeg render retry (no %s) also failed (rc=%d):\n%s",
                          token, result.returncode,
                          result.stderr.decode(errors="replace")[-3000:])

        return False

    def _get_duration(self) -> float | None:
        cmd = [
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "csv=p=0", self.input_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except (ValueError, AttributeError):
            return None


def _track_font_usage(font_path: Path) -> None:
    """Best-effort usage_count bump on the matching `assets` row (type=font),
    matched by filename — one list_assets call per edit_single() invocation
    (once per reel, never per-frame). Never raises; purely analytics."""
    try:
        from backend.db import list_assets, increment_asset_usage
        row = next((r for r in list_assets("font") if r.get("filename") == font_path.name), None)
        if row and row.get("id"):
            increment_asset_usage(row["id"])
    except Exception as exc:
        log.debug("video_edit: font usage tracking skipped (non-fatal): %s", exc)


def load_template(category: str) -> dict | None:
    template_file = TEMPLATES_DIR / f"{category}.json"
    if not template_file.exists():
        return None
    return json.loads(template_file.read_text())


def edit_single(item: dict, music_path: str | None = None, replace_audio: bool = False,
                music_source: str | None = None, lut_override: str | None = None,
                music_start: float | None = None, no_lut: bool = False,
                keep_original_audio: bool = False,
                edl_overrides: dict | None = None) -> dict:
    """Composite + encode the final reel.

    `edl_overrides` is the second half of `editor_edl.compile()` (an
    EditOverrides dump) and is present only for a reel-editor export. When it is
    set, the EDL is authoritative for everything it covers — colour grade,
    branding/voiceover/intro/cast toggles and the overlay layers — because the
    user made those decisions explicitly in the timeline. The settings-driven
    defaults below still run for everything the EDL does not model (quality
    chain, encode params, music decision).
    """
    mid = item.get("id")
    log.info("edit: media_id=%s start (category=%s arc=%s)",
             mid, item.get("category"), item.get("series_arc_position"))
    reel_path = item.get("reel_ready_path")
    if not reel_path or not Path(reel_path).exists():
        log.error("edit: media_id=%s FAILED at input: reel_ready_path missing on disk (%r) "
                  "— fix: re-run the resize stage to regenerate the 9:16 reel before editing",
                  mid, reel_path)
        update_status(item["id"], "error", "no_reel_file")
        return {"status": "error", "reason": "no_reel_file"}

    category = item.get("category", "hidden_gem")
    tags = item.get("tags") or []

    # Hashtags: top 2 EN tags as subtitle overlay (strip leading #)
    raw_hashtags = item.get("hashtags_en") or []
    if isinstance(raw_hashtags, str):
        import json as _json
        try:
            raw_hashtags = _json.loads(raw_hashtags)
        except Exception:
            raw_hashtags = []
    hashtag_text = "  ".join(f"#{t.lstrip('#')}" for t in raw_hashtags[:2]) if raw_hashtags else ""

    output_path = str(Path(reel_path).with_name(f"{item['id']}_edited.mp4"))

    editor = VideoEditor(reel_path)

    profile = CATEGORY_PROFILE.get(category, _DEFAULT_PROFILE)
    arc = item.get("series_arc_position")          # opener / build / climax / closer
    hook = _hook_overlay(item)                      # Enhancement F: caption-derived hook
    episode_marker = _episode_marker(item)          # Enhancement F: "Day 3 of 8 in nature"
    clip_len = editor._get_duration() or 15

    template = load_template(category)
    intro = template.get("intro", {}) if template else {}
    body = template.get("body", {}) if template else {}

    # Track 1 video-quality chain (Enh K): free CPU-only FFmpeg filters. Denoise
    # runs FIRST (before motion/scale) so zoom doesn't amplify grain; sharpen +
    # optional smooth-motion run LAST (after the LUT). All gated via the "video"
    # settings group so intensity is tunable per account.
    vcfg = get_setting("video") or {}
    quality_on = vcfg.get("enhance_quality", True)
    if quality_on and vcfg.get("denoise", True):
        editor.apply_denoise(vcfg.get("denoise_strength", "light"))

    # Enhancement H: motion tuned per category; openers/climax always get a push,
    # climax zooms harder for emphasis.
    zoom_end = profile["zoom_end"]
    if arc == "climax":
        zoom_end = min(zoom_end + 0.1, 1.5)
    if body.get("ken_burns") or arc in ("opener", "climax"):
        editor.apply_ken_burns(zoom_end=zoom_end, duration=clip_len)

    # Content-aware LUT pick (mode + mood/vision per the "color" settings group);
    # lut_override is a manual pick from the Preview edit drawer. Always degrades
    # to the legacy CATEGORY_LUT map → never grades worse than before.
    # Merged reels that were already film-graded at merge time skip the LUT so the
    # OpenMontage grade stays the single coherent look (no double-grade).
    _meta = item.get("metadata")
    if isinstance(_meta, str):
        try:
            _meta = json.loads(_meta)
        except Exception:
            _meta = {}
    _merge_graded = (item.get("source") == "merge"
                     and isinstance(_meta, dict)
                     and (_meta.get("merge") or {}).get("graded"))
    # no_lut: manual create wizard chose no colour grade → keep the original video
    # look (no LUT at all). Skips even the auto/category fallback. An explicit
    # lut_override still wins over no_lut (user picked a specific grade).
    if edl_overrides is not None:
        # eq goes BEFORE the LUT: the grade is authored against corrected
        # exposure, and swapping the order changes the look. FFmpeg `eq`
        # brightness is ADDITIVE in [-1,1] while contrast/saturation are
        # multiplicative — the editor's WebGL preview uses the same formula.
        # Clamped again here even though EqSpec already validates: this string
        # goes straight into a filtergraph, so it never trusts its caller.
        eq = edl_overrides.get("eq") or {}
        b = _clamp(_num(eq.get("brightness"), 0.0), -1.0, 1.0)
        c = _clamp(_num(eq.get("contrast"), 1.0), 0.0, 3.0)
        s = _clamp(_num(eq.get("saturation"), 1.0), 0.0, 3.0)
        if (b, c, s) != (0.0, 1.0, 1.0):
            editor.filters.append(
                f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={s:.3f}")

    if edl_overrides is not None:
        # Editor export: the EDL's LUT choice is final, including "no LUT". The
        # category/mood auto-pick must not sneak a grade back in — the user saw an
        # ungraded preview and exported that.
        edl_lut = edl_overrides.get("lut")
        if edl_lut:
            editor.apply_lut(edl_lut)     # absolute, containment-checked in compile()
        else:
            log.info("video_edit: editor export — no LUT on the EDL for %s", item.get("id"))
    elif no_lut and not lut_override:
        log.info("video_edit: no_lut — skip colour grade for %s", item.get("id"))
    elif _merge_graded and not lut_override:
        log.info("video_edit: skip LUT for graded merge reel %s", item.get("id"))
    else:
        from backend.pipeline.lut_select import select_lut
        lut_file = select_lut(item, get_setting("color") or {}, override=lut_override)
        if lut_file:
            editor.apply_lut(lut_file)

    if quality_on and vcfg.get("sharpen", True):
        editor.apply_sharpen(vcfg.get("sharpen_amount", 0.4))
    # Smooth-motion is CPU-heavy → opt-in (off by default).
    if quality_on and vcfg.get("smooth_motion", False):
        editor.apply_smooth(int(vcfg.get("smooth_fps", 60)))

    # Branding overlay: full-width bar with location, @handle, and optional custom text.
    # Must be appended LAST so it composites on top of the colour grade.
    bcfg = get_setting("branding") or {}
    branding_on = bcfg.get("overlay_enabled", False)
    if edl_overrides is not None:
        branding_on = branding_on and bool(edl_overrides.get("branding", True))
    if branding_on:
        from backend.pipeline.overlay import format_tags, build_branding_filters
        selected_font = (bcfg.get("font") or "").strip()
        font_path = FONTS_DIR / selected_font if selected_font else FONTS_DIR / "PlayfairDisplay-SemiBold.ttf"
        if not font_path.exists():
            font_path = FONTS_DIR / "PlayfairDisplay-SemiBold.ttf"
        if not font_path.exists():
            # Bind-mount overrides /app/assets at runtime — fall back to a font
            # installed directly in the Docker image (not subject to the mount).
            font_path = Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf")
        if font_path.exists():
            _track_font_usage(font_path)
            loc = format_tags(tags)
            handle = (bcfg.get("ig_handle") or "").strip()
            editor.filters.extend(
                build_branding_filters(
                    loc, handle,
                    bar_h=int(bcfg.get("bar_height", 45)),
                    font_path=str(font_path),
                    bar_bg_color=str(bcfg.get("bar_bg_color", "#ffffff")),
                    text_color=str(bcfg.get("text_color", "#000000")),
                    bar_opacity=float(bcfg.get("bar_opacity", 1.0)),
                    bar_position=str(bcfg.get("bar_position", "bottom")),
                    location_side=str(bcfg.get("location_side", "left")),
                    handle_side=str(bcfg.get("handle_side", "right")),
                    custom_text=str(bcfg.get("custom_text", "")),
                    font_size=int(bcfg.get("font_size", 0)),
                )
            )
        else:
            log.warning(
                "edit: media_id=%s branding overlay skipped — no font found "
                "(rsync assets/fonts/ to server or rebuild Docker image)",
                mid,
            )

    # Voiceover (1.8.0): edge-tts narration + word-synced burned subtitles.
    # keep_original_audio (manual "keep original" pick) suppresses voiceover too,
    # same override that already suppresses auto background music above.
    vocfg = get_setting("voiceover") or {}
    voiceover_path = item.get("voiceover_path")
    voiceover_srt_path = item.get("voiceover_srt_path")
    apply_voiceover = bool(
        not keep_original_audio
        and vocfg.get("enabled", False)
        and voiceover_path and Path(voiceover_path).exists()
        # An editor export can turn narration off for this reel only.
        and (edl_overrides is None or edl_overrides.get("voiceover", False))
    )
    if apply_voiceover and vocfg.get("subtitles_enabled", True) and voiceover_srt_path and Path(voiceover_srt_path).exists():
        # Appended after branding so subtitles composite on top of the branding
        # bar/grade, but still before the intro/cast fold below (same single
        # ffmpeg pass as those screens).
        editor.filters.append(_subtitle_filter(voiceover_srt_path, vocfg))

    # The editor's audio lane can set the duck level per reel; None keeps the
    # global `voiceover.music_duck_volume`.
    duck_vol = _num(vocfg.get("music_duck_volume"), 0.08)
    if edl_overrides is not None and edl_overrides.get("music_duck_volume") is not None:
        duck_vol = _clamp(_num(edl_overrides["music_duck_volume"], duck_vol), 0.0, 1.0)

    applied_music = False
    if music_path and Path(music_path).exists():
        audio_conf = template.get("audio", {}) if template else {}
        # Auto-added music (replace_audio) plays at full volume since it is the
        # only track; music mixed under existing audio stays quiet. When a
        # voiceover is also present it becomes the primary spoken track, so the
        # music bed (regardless of replace_audio) drops to the configured duck level.
        if apply_voiceover:
            vol = duck_vol
        else:
            vol = 1.0 if replace_audio else audio_conf.get("volume", 0.15)
        editor.add_background_music(music_path, volume=vol, replace=replace_audio,
                                    start_offset=music_start)
        applied_music = True

    if apply_voiceover:
        editor.add_voiceover(voiceover_path, duck_volume=duck_vol)

    # Encode quality: bump CRF (lower=better) + slower preset when the quality
    # chain is on; fall back to the lightweight legacy encode otherwise.
    crf = int(vcfg.get("crf", 20)) if quality_on else 22
    preset = vcfg.get("preset", "medium") if quality_on else "fast"
    # C2: load intro/cast config before render so generated screens can be
    # folded into the editor's filter chain (one encode pass instead of two).
    icfg = get_setting("intro") or {}
    ccfg = get_setting("cast") or {}
    # B4: loop-friendly merge → suppress cast so the reel loops cleanly back to the opener.
    if (isinstance(_meta, dict) and (_meta.get("merge") or {}).get("loop_friendly")):
        ccfg = {**ccfg, "enabled": False}

    intro_enabled = icfg.get("enabled", False)
    cast_enabled = ccfg.get("enabled", False)
    if edl_overrides is not None:
        # The editor shows intro/cast as reel toggles; honour them per export.
        intro_enabled = bool((edl_overrides.get("intro") or {}).get("enabled", intro_enabled))
        cast_enabled = bool((edl_overrides.get("cast") or {}).get("enabled", cast_enabled))
    intro_is_asset = icfg.get("mode", "generated") == "asset"
    cast_is_asset = ccfg.get("mode", "generated") == "asset"
    # Asset-mode screens need a separate overlay pass; generated screens fold into the editor.
    use_asset_pass = (intro_enabled and intro_is_asset) or (cast_enabled and cast_is_asset)

    if not use_asset_pass and (intro_enabled or cast_enabled):
        # C2: attach generated intro/cast drawtext/drawbox filters to the editor
        # so they encode in the same ffmpeg pass — no second subprocess.
        try:
            from backend.pipeline.screens import (
                _screen_draw_filters, _collect_intro_elements, _collect_cast_elements,
            )
            dur = editor._get_duration() or 0.0
            if intro_enabled:
                raw = _collect_intro_elements(item, icfg)
                if raw:
                    d = max(0.5, float(icfg.get("duration_s", 1.5)))
                    fd = min(0.5, d / 3) if icfg.get("animation", "fade") != "none" else 0.0
                    editor.filters.extend(_screen_draw_filters(raw, icfg, 0.0, d, fd))
            if cast_enabled and dur > 0:
                raw = _collect_cast_elements(item, ccfg)
                if raw:
                    cd = max(0.5, float(ccfg.get("duration_s", 1.5)))
                    cs = max(0.0, dur - cd)
                    fd = min(0.5, cd / 3) if ccfg.get("animation", "fade") != "none" else 0.0
                    editor.filters.extend(_screen_draw_filters(raw, ccfg, cs, dur, fd))
        except Exception:
            log.exception("edit: media_id=%s failed to attach screens to editor", mid)

    # Editor overlay layers go on LAST so they composite above the grade, the
    # branding bar, subtitles and the intro/cast screens — the timeline shows
    # them as the topmost lanes and the render must agree.
    if edl_overrides is not None:
        try:
            from backend.pipeline import editor_layers
            text_layers = edl_overrides.get("text_layers") or []
            if text_layers:
                files = editor_layers.write_text_files(str(mid), text_layers)
                editor.filters.extend(editor_layers.build_text_filters(text_layers, files))
            # Images composite ABOVE text: they run as overlays after the whole
            # -vf chain (which is where drawtext lives), so a logo/watermark is
            # never hidden behind a caption. compile() already z-sorted them.
            for layer in edl_overrides.get("image_layers") or []:
                asset_path = layer.get("asset_path")
                if not asset_path:
                    # Only compile() can produce a containment-checked absolute
                    # path; falling back to the relative `asset` would hand
                    # ffmpeg whatever the user typed. Drop the layer instead.
                    log.warning("edit: media_id=%s image layer %s has no resolved "
                                "asset_path — skipped", mid, layer.get("id"))
                    continue
                editor.add_image_overlay(
                    asset_path,
                    x=_num(layer.get("x"), 0.5), y=_num(layer.get("y"), 0.5),
                    w=layer.get("w"), h=layer.get("h"),
                    opacity=_num(layer.get("opacity"), 1.0),
                    start_s=_num(layer.get("start_s"), 0.0),
                    end_s=_num(layer.get("end_s"), 0.0),
                )
        except Exception:
            # A broken overlay must not cost the whole reel — it publishes
            # without the layer and the failure is in the log.
            log.exception("edit: media_id=%s failed to attach editor text layers", mid)

    success = editor.render(output_path, crf=crf, preset=preset)
    if success:
        final_path = output_path
        if use_asset_pass and (intro_enabled or cast_enabled):
            # Asset-mode screens still require a separate overlay pass.
            try:
                from backend.pipeline.screens import render_screens
                final_path = render_screens(item, icfg, ccfg, output_path, out_dir=REELS_READY_DIR)
            except Exception:
                log.exception("edit: media_id=%s screens render failed — using body-only reel", mid)
                final_path = output_path

        update = {"status": "edited", "reel_ready_path": final_path}
        if music_source:
            update["music_source"] = music_source
        if applied_music:
            update["licensed_music"] = Path(music_path).name
        update_media(item["id"], update)
        # Clean up pre-concat body file now that _final.mp4 is canonical.
        if final_path != output_path:
            try:
                Path(output_path).unlink(missing_ok=True)
                log.info("edit: media_id=%s deleted pre-concat body %s", mid, Path(output_path).name)
            except OSError:
                pass
        # Delete the input source (typically _enhanced.mp4, or _9x16.mp4 when
        # enhance was skipped) now that the edited reel is canonical in the DB.
        # Guard against accidental deletion of the output itself.
        if reel_path and Path(reel_path).exists() and Path(reel_path).resolve() not in {
            Path(output_path).resolve(), Path(final_path).resolve()
        }:
            try:
                Path(reel_path).unlink(missing_ok=True)
                log.info("edit: media_id=%s deleted enhanced input %s", mid, Path(reel_path).name)
            except OSError:
                pass
        log.info("edit: media_id=%s ok → %s (music=%s crf=%d preset=%s)",
                 mid, final_path, applied_music, crf, preset)
        return {"status": "edited", "output": final_path}
    else:
        log.error("edit: media_id=%s FAILED at render: ffmpeg returned non-zero (output=%r) "
                  "— check the ffmpeg error logged above", mid, output_path)
        update_status(item["id"], "error", "ffmpeg_edit_failed")
        return {"status": "error", "reason": "ffmpeg_failed"}


def _music_decision(item: dict) -> tuple[str | None, bool, str]:
    """Decide whether a clip needs auto background music.

    Returns (music_path, replace_audio, music_source). music_path is None →
    leave the clip's audio untouched (it already has real music or pleasant
    ambient). When set, the track replaces the original audio — covers clips
    with no audio stream, near-silent clips, and speech/noise-dominant clips
    (talking, loud voices, raw camera mic).

    music_source is the final-state label written to media.music_source:
        'licensed' — category track applied
        'original' — clip's own music/ambient kept
        'none'     — needs music but no track available (or no audio at all)
    """
    # Merged reels already carry their single music bed (muxed in merge_clips) —
    # never add a second track on top.
    if item.get("source") == "merge":
        return None, False, "original"
    reel_path = item.get("reel_ready_path")
    if not reel_path or not Path(reel_path).exists():
        return None, False, "unknown"
    try:
        from backend.pipeline.audio_probe import classify
        info = classify(reel_path)
        category = info.get("category", "unknown")
        if not info.get("needs_music"):
            # Real music or pleasant ambient — keep it.
            return None, False, "original"
    except Exception:
        return None, False, "unknown"

    try:
        from backend.pipeline.music_fetcher import get_track_for_category
        # Caption-mood matching (Enh G): derive a mood from text the raw clip
        # already has (original IG caption + tags) — the generated caption isn't
        # ready at the edit stage. Gated; None mood → category-only behaviour.
        mood = None
        item_tags = item.get("tags")
        if (get_setting("music") or {}).get("mood_match", True):
            from backend.pipeline.music_mood import mood_from_text
            tags_text = " ".join(item_tags) if isinstance(item_tags, list) else (item_tags or "")
            mood = mood_from_text(item.get("original_caption"), tags_text)
        # Pass clip length so the selector can prefer tracks that cover the clip.
        clip_len = _media_duration(reel_path) if reel_path else None
        track = get_track_for_category(item.get("category", "hidden_gem"),
                                     tags=item_tags if isinstance(item_tags, list) else None,
                                     clip_len=clip_len,
                                     mood=mood)
        if track:
            return track, True, "licensed"
        # Needed music but none available: reflect that nothing plays.
        return None, False, "none"
    except Exception:
        return None, False, "none"


def run(media_id=None, lut_override: str | None = None,
        music_override: str | None = None, music_start: float | None = None,
        keep_original_audio: bool = False, no_lut: bool = False,
        edl_overrides: dict | None = None):
    run_log = log_pipeline_run("video_edit")
    edited = 0
    failed = 0

    if media_id:
        item = get_media_by_id(media_id)
        items = [item] if item else []
    else:
        # Prefer enhanced (new pipeline); fall back to resized (legacy / enhance skipped)
        items = get_media(filters={"status": "enhanced"})
        if not items:
            items = get_media(filters={"status": "resized"})

    for item in items:
        # A manual music swap (Preview edit drawer) overrides the auto decision,
        # and replaces the existing bed — including for merged reels whose music
        # is otherwise baked in and skipped by _music_decision.
        if music_override and Path(music_override).exists():
            music_path, replace_audio, music_source = music_override, True, "licensed"
        elif keep_original_audio:
            # Manual create wizard picked no track → keep the clip's own audio
            # untouched (no auto-added bed). Bypasses _music_decision entirely.
            music_path, replace_audio, music_source = None, False, "original"
        else:
            music_path, replace_audio, music_source = _music_decision(item)
        result = edit_single(item, music_path=music_path, replace_audio=replace_audio,
                             music_source=music_source, lut_override=lut_override,
                             music_start=music_start, no_lut=no_lut,
                             keep_original_audio=keep_original_audio,
                             edl_overrides=edl_overrides)
        if result["status"] == "edited":
            edited += 1
        else:
            failed += 1

    result = {"edited": edited, "failed": failed, "total": len(items)}
    if run_log:
        from datetime import datetime, timezone
        update_pipeline_run(run_log["id"], {
            "status": "completed" if not failed else "failed",
            "items_processed": edited,
            "items_failed": failed,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-id", help="Edit single media item")
    args = parser.parse_args()
    result = run(media_id=args.media_id)
    print(f"Edited: {result['edited']}/{result['total']}. Failed: {result['failed']}")
