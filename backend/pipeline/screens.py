"""
Intro (splash) and Cast (outro) screen builders for the reel pipeline.

build_intro_clip / build_cast_clip: generate or normalize a short 1080x1920
screen clip for overlay use.

render_screens: entry point. Generated intro/cast are BURNED onto the body via
burn_screens (drawbox tint + time-gated drawtext with an alpha-fade expression) —
one video stream, so the live video plays under the text with no frozen still, no
flicker, and no added duration. Asset-mode splash files (uploaded clips) use
overlay_screens (clip-overlay) on top of the burned result.
"""

import logging
import random as _random
import subprocess
import threading
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

_RENDER_SEM = threading.Semaphore(2)   # allow 2 concurrent encodes per stage

# Shared output dimensions — must match resize_clips.py profile.
_W, _H = 1080, 1920
_FPS = 30


_ANIMATION_CHOICES = ["fade", "zoom", "slide", "blur", "wipe", "ken_burns"]


def _animation_filters(animation: str, duration: float) -> list[str]:
    """Return FFmpeg filter strings to apply the animation to an overlay clip.

    Filters are applied to the overlay input in the filter graph BEFORE the
    overlay step. Alpha-based animations output yuva420p so overlay composites
    through the alpha channel, avoiding the black-flash that baked fade caused.
    """
    anim = animation if animation != "random" else _random.choice(_ANIMATION_CHOICES)

    d   = float(max(0.5, duration))
    fd  = min(0.40, d / 4)          # transition window (in + out), seconds

    d_s  = f"{d:.3f}"
    fd_s = f"{fd:.3f}"

    # Alpha expression: 0 → 255 over fd, hold 255, 255 → 0 over fd
    _alpha_fade = (
        f"255*clip(T/{fd_s},0,1)"
        f"*if(gt(T,{d_s}-{fd_s}),clip(({d_s}-T)/{fd_s},0,1),1)"
    )

    if anim == "fade":
        return [
            "format=yuva420p",
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{_alpha_fade}'",
        ]

    elif anim == "zoom":
        # d=1: one output frame per input frame (preserves clip length).
        # Zoom animates via `on` (output frame counter), NOT via d.
        return [
            f"zoompan=z='min(1+0.018*on/{_FPS},1.18)'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={_W}x{_H}:fps={_FPS}",
            "format=yuva420p",
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{_alpha_fade}'",
        ]

    elif anim == "slide":
        # Reveal bottom-to-top on entry; hide top-to-bottom on exit (row-level alpha)
        a_in  = f"if(gte(Y,{_H}*(1-min(T/{fd_s},1))),255,0)"
        a_out = f"if(lt(Y,{_H}*max(0,(T-({d_s}-{fd_s}))/{fd_s})),0,255)"
        alpha = f"if(lt(T,{fd_s}),{a_in},if(gt(T,{d_s}-{fd_s}),{a_out},255))"
        return [
            "format=yuva420p",
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha}'",
        ]

    elif anim == "blur":
        # Soft static blur combined with alpha fade (gblur sigma is not dynamic)
        return [
            "gblur=sigma=6",
            "format=yuva420p",
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{_alpha_fade}'",
        ]

    elif anim == "wipe":
        # Reveal left-to-right on entry; hide left-to-right on exit (column-level alpha)
        a_in  = f"if(lte(X,{_W}*min(T/{fd_s},1)),255,0)"
        a_out = f"if(lte(X,{_W}*(1-max(0,(T-({d_s}-{fd_s}))/{fd_s}))),255,0)"
        alpha = f"if(lt(T,{fd_s}),{a_in},if(gt(T,{d_s}-{fd_s}),{a_out},255))"
        return [
            "format=yuva420p",
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha}'",
        ]

    elif anim == "ken_burns":
        # d=1: one output frame per input frame (preserves clip length).
        x = f"iw/2-(iw/zoom/2)+iw*0.04*sin(on*6.2832/{_FPS}/4)"
        y = f"ih/2-(ih/zoom/2)+ih*0.025*sin(on*6.2832/{_FPS}/7)"
        return [
            f"zoompan=z='min(1+0.012*on/{_FPS},1.14)':x='{x}':y='{y}':d=1:s={_W}x{_H}:fps={_FPS}",
            "format=yuva420p",
            f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{_alpha_fade}'",
        ]

    return []   # "none" or unknown — raw clip passed straight to overlay


def _run(cmd: list[str], label: str) -> bool:
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        log.error("%s failed (rc=%d):\n%s", label, result.returncode,
                  result.stderr.decode(errors="replace")[-2000:])
        return False
    return True


def _resolve_font(font_name: str) -> str | None:
    """Resolve a font filename to an absolute path, with fallbacks."""
    from backend.config import FONTS_DIR
    candidates = []
    if font_name:
        candidates.append(FONTS_DIR / font_name)
    candidates += [
        FONTS_DIR / "PlayfairDisplay-SemiBold.ttf",
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _css_to_ffmpeg_color(hex_color: str, opacity: float = 1.0) -> str:
    """Convert #RRGGBB to 0xRRGGBB@opacity for FFmpeg color params."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        return f"0x{h.upper()}@{opacity:.2f}"
    return f"0xFFFFFF@{opacity:.2f}"


def _grab_frame(video_path: str, output_path: str, ss: float = 0.5) -> bool:
    """Extract a single frame from a video at the given seek position."""
    cmd = [
        "ffmpeg", "-hide_banner",
        "-ss", str(ss), "-i", video_path,
        "-vframes", "1",
        "-y", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0 and Path(output_path).exists()


def _escape_drawtext(text: str) -> str:
    """Escape FFmpeg drawtext special characters."""
    return (
        text.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace(":", "\\:")
            .replace("'", "\\'")
    )


def _compute_drawtext_items(
    elements: list[dict],
    text_padding_h: int,
) -> list[dict]:
    """Compute Y positions for all text lines across all elements.

    Each element dict: {text, color, font_path, font_size, bottom_padding?}
    Returns list of {text, font_path, font_size, color, y, padding}.
    """
    gap_elem = 24   # px between elements
    gap_line = 10   # px between lines within an element

    # Expand each element's text into lines
    blocks: list[dict] = []
    for el in elements:
        raw_lines = [ln for ln in el["text"].split("\n") if ln.strip()]
        if not raw_lines:
            continue
        lh = int(el["font_size"] * 1.25)
        block_h = len(raw_lines) * lh + max(0, len(raw_lines) - 1) * gap_line
        blocks.append({
            "lines": raw_lines,
            "font_path": el["font_path"],
            "font_size": el["font_size"],
            "color": el["color"],
            "lh": lh,
            "block_h": block_h,
            "bottom_padding": int(el.get("bottom_padding", 0)),
        })

    if not blocks:
        return []

    total_h = (
        sum(b["block_h"] + b["bottom_padding"] for b in blocks)
        + gap_elem * (len(blocks) - 1)
    )
    cur_y = (_H - total_h) // 2

    items: list[dict] = []
    for i, block in enumerate(blocks):
        for j, line in enumerate(block["lines"]):
            y = cur_y + j * (block["lh"] + gap_line)
            items.append({
                "text": line,
                "font_path": block["font_path"],
                "font_size": block["font_size"],
                "color": block["color"],
                "y": y,
                "padding": text_padding_h,
            })
        cur_y += block["block_h"] + block["bottom_padding"]
        if i < len(blocks) - 1:
            cur_y += gap_elem

    return items


def _build_transparent_clip(
    output_path: str,
    duration_s: float,
    bg_color: str,
    bg_opacity: float,
    text_padding_h: int,
    elements: list[dict],
    animation: str,
) -> bool:
    """Render a generated text card on a FULLY TRANSPARENT canvas for OVERLAY use.

    The card is text (+ an optional bg_opacity colour tint) on alpha=0 elsewhere,
    so when composited over the body reel the live, moving video shows through for
    the whole intro/cast window — no frozen still, no added duration. Encoded to a
    .mov with the qtrle codec (lossless, carries an alpha channel; H.264 cannot).
    """
    d = max(0.5, float(duration_s))
    dt_items = _compute_drawtext_items(elements, text_padding_h)

    # Transparent RGBA canvas.
    vf_parts: list[str] = ["format=rgba"]

    # Optional colour tint over the whole frame (alpha = bg_opacity). 0 = no tint
    # → pure text over video. Honors intro.bg_opacity / cast.bg_opacity.
    if bg_opacity and bg_opacity > 0:
        tint = _css_to_ffmpeg_color(bg_color, bg_opacity)
        vf_parts.append(f"drawbox=x=0:y=0:w=iw:h=ih:color={tint}:t=fill")

    for item in dt_items:
        tc = _css_to_ffmpeg_color(item["color"])
        t = _escape_drawtext(item["text"])
        fp = item["font_path"].replace("'", "\\'")
        x_expr = f"max({item['padding']}\\,(w-text_w)/2)"
        vf_parts.append(
            f"drawtext=fontfile='{fp}':text='{t}':fontsize={item['font_size']}:fontcolor={tc}"
            f":x={x_expr}:y={item['y']}:shadowcolor=black@0.4:shadowx=2:shadowy=2"
        )

    # Bake an alpha fade in/out at the edges (alpha=1 fades the alpha channel only,
    # preserving the per-pixel text/tint transparency during the hold).
    if animation and animation != "none":
        fd = min(0.5, d / 3)
        vf_parts.append(
            f"fade=t=in:st=0:d={fd:.2f}:alpha=1,fade=t=out:st={d - fd:.2f}:d={fd:.2f}:alpha=1"
        )

    vf = ",".join(vf_parts)
    cmd = [
        "ffmpeg", "-hide_banner",
        "-f", "lavfi", "-i", f"color=c=black@0.0:s={_W}x{_H}:r={_FPS}:d={d}",
        "-vf", vf,
        "-c:v", "qtrle",
        "-an",
        "-t", str(d),
        "-y", output_path,
    ]
    return _run(cmd, f"build_transparent_clip({output_path})")


def _build_generated_clip(
    output_path: str,
    duration_s: float,
    bg_color: str,
    bg_opacity: float,
    text_padding_h: int,
    elements: list[dict],   # [{text, color, font_path, font_size, bottom_padding?}] sorted by order
    animation: str,
    source_frame: str | None = None,
) -> bool:
    """Render a generated text-card clip.

    When source_frame is provided the frame is used as the backdrop and bg_color/bg_opacity
    are applied as a drawbox overlay, so bg_opacity < 1.0 makes the video show through.
    Without a source_frame the clip falls back to a solid lavfi color source.
    """
    bg = _css_to_ffmpeg_color(bg_color, bg_opacity)
    d = max(0.5, float(duration_s))

    dt_items = _compute_drawtext_items(elements, text_padding_h)

    vf_parts: list[str] = []

    if source_frame:
        # Scale grabbed frame to target resolution, then draw semi-transparent colour box.
        vf_parts.append(f"scale={_W}:{_H}:flags=lanczos,setsar=1")
        vf_parts.append(f"drawbox=x=0:y=0:w=iw:h=ih:color={bg}:t=fill")

    if animation == "fade":
        fade_d = min(0.5, d / 3)
        vf_parts.append(
            f"fade=t=in:st=0:d={fade_d:.2f},fade=t=out:st={d - fade_d:.2f}:d={fade_d:.2f}"
        )
    elif animation == "zoom":
        # d=1: one output frame per input frame (matches _animation_filters fix).
        vf_parts.append(
            f"zoompan=z='min(zoom+0.0015,1.2)':d=1:s={_W}x{_H}:fps={_FPS}"
        )

    for item in dt_items:
        tc = _css_to_ffmpeg_color(item["color"])
        t = _escape_drawtext(item["text"])
        fp = item["font_path"].replace("'", "\\'")
        fs = item["font_size"]
        y = item["y"]
        pad = item["padding"]
        # Comma inside max() must be escaped as \, for FFmpeg filter graph parser
        x_expr = f"max({pad}\\,(w-text_w)/2)"
        vf_parts.append(
            f"drawtext=fontfile='{fp}':text='{t}':fontsize={fs}:fontcolor={tc}"
            f":x={x_expr}:y={y}:shadowcolor=black@0.4:shadowx=2:shadowy=2"
        )

    vf = ",".join(vf_parts) if vf_parts else "null"

    if source_frame:
        cmd = [
            "ffmpeg", "-hide_banner",
            "-loop", "1", "-t", str(d), "-i", source_frame,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(d),
            "-movflags", "+faststart",
            "-y", output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-hide_banner",
            "-f", "lavfi", "-i", f"color={bg}:s={_W}x{_H}:r={_FPS}:d={d}",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(d),
            "-movflags", "+faststart",
            "-y", output_path,
        ]
    return _run(cmd, f"build_generated_clip({output_path})")


def _normalize_asset(src: str, output_path: str, duration_s: float) -> bool:
    """Normalize an uploaded image or video asset to 1080x1920 H.264/AAC.

    Uses the same crop+scale recipe as resize_clips.py so concat works cleanly.
    For images: static hold for duration_s. For videos: trim/pad to duration_s.
    """
    p = Path(src)
    ext = p.suffix.lower()
    d = max(0.5, float(duration_s))

    if ext in (".jpg", ".jpeg", ".png"):
        cmd = [
            "ffmpeg", "-hide_banner",
            "-loop", "1", "-i", src,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={_W}:{_H}:flags=lanczos,setsar=1,fps={_FPS}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(d),
            "-movflags", "+faststart",
            "-y", output_path,
        ]
    else:
        # Use anullsrc as audio source so this works even when the uploaded
        # asset has no audio stream.
        vf = (
            f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale={_W}:{_H}:flags=lanczos,"
            f"setsar=1,fps={_FPS}"
        )
        fc = (
            f"[0:v]{vf}[vout];"
            f"[1:a]apad=whole_dur={d}[aout]"
        )
        cmd = [
            "ffmpeg", "-hide_banner",
            "-i", src,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-filter_complex", fc,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(d),
            "-movflags", "+faststart",
            "-y", output_path,
        ]
    return _run(cmd, f"normalize_asset({src})")


def _get_element_font(cfg: dict, font_key: str) -> str | None:
    return _resolve_font((cfg.get(font_key) or "").strip())


def _make_elem(raw: list[dict], cfg: dict):
    """Return an _elem(text, ...) appender bound to *raw* and *cfg*."""
    def _elem(text: str, color_key: str, font_key: str, size_key: str, order_key: str,
              default_size: int, bottom_padding: int = 0) -> None:
        if not text:
            return
        fp = _get_element_font(cfg, font_key) or _resolve_font("")
        if not fp:
            return
        raw.append({
            "text": text,
            "color": cfg.get(color_key, "#ffffff"),
            "font_path": fp,
            "font_size": int(cfg.get(size_key, default_size)),
            "order": int(cfg.get(order_key, len(raw))),
            "bottom_padding": bottom_padding,
        })
    return _elem


def _collect_intro_elements(item: dict, cfg: dict) -> list[dict]:
    """Build the ordered list of intro text elements (no rendering)."""
    from backend.db import get_setting
    handle = ((get_setting("branding") or {}).get("ig_handle") or "").strip()
    tags = item.get("tags") or []
    tags_text = ", ".join(tags) if isinstance(tags, list) else (tags or "")
    category = item.get("category", "")

    raw: list[dict] = []
    _elem = _make_elem(raw, cfg)

    if cfg.get("show_hook", False):
        hook_source = (cfg.get("hook_source") or "caption_line1").strip()
        hook_text = ""
        if hook_source == "caption_line1":
            raw_caption = (item.get("caption") or "").strip()
            for line in raw_caption.splitlines():
                line = line.strip()
                if line:
                    hook_text = line
                    break
        else:  # "manual"
            hook_text = (cfg.get("hook_text") or "").strip()
        if hook_text:
            _elem(hook_text, "hook_color", "hook_font", "hook_font_size", "hook_order", 56,
                  bottom_padding=int(cfg.get("hook_bottom_padding") or 24))

    if cfg.get("header_enabled", True):
        header_text = (cfg.get("header_text") or "").strip() or handle
        _elem(header_text, "header_color", "header_font", "header_font_size", "header_order", 52,
              bottom_padding=int(cfg.get("header_bottom_padding") or 0))
    if cfg.get("subheader_enabled", True):
        _elem((cfg.get("subheader_text") or "").strip(), "subheader_color", "subheader_font",
              "subheader_font_size", "subheader_order", 36,
              bottom_padding=int(cfg.get("subheader_bottom_padding") or 16))
    if cfg.get("show_tags", True) and tags_text:
        _elem(tags_text, "tags_color", "tags_font", "tags_font_size", "tags_order", 40,
              bottom_padding=int(cfg.get("tags_bottom_padding") or 0))
    if cfg.get("show_category", True) and category:
        _elem(category.replace("_", " ").title(), "category_color", "category_font", "category_font_size",
              "category_order", 30, bottom_padding=int(cfg.get("category_bottom_padding") or 0))
    if cfg.get("show_handle", True) and handle:
        _elem(handle, "handle_color", "handle_font", "handle_font_size", "handle_order", 28,
              bottom_padding=int(cfg.get("handle_bottom_padding") or 0))

    raw.sort(key=lambda e: e["order"])
    return raw


def _collect_cast_elements(item: dict, cfg: dict) -> list[dict]:
    """Build the ordered list of cast/outro text elements (no rendering)."""
    from backend.db import get_setting
    handle = ((get_setting("branding") or {}).get("ig_handle") or "").strip()
    tags = item.get("tags") or []
    tags_text = ", ".join(tags) if isinstance(tags, list) else (tags or "")

    raw: list[dict] = []
    _elem = _make_elem(raw, cfg)

    minimal = cfg.get("minimal_cta", False)

    if cfg.get("cta_enabled", True):
        _elem((cfg.get("cta_text") or "Follow for more").strip(), "cta_color", "cta_font",
              "cta_font_size", "cta_order", 52, bottom_padding=int(cfg.get("cta_bottom_padding") or 0))
    if not minimal and cfg.get("subheader_enabled", True):
        _elem((cfg.get("subheader_text") or "").strip(), "subheader_color", "subheader_font",
              "subheader_font_size", "subheader_order", 36,
              bottom_padding=int(cfg.get("subheader_bottom_padding") or 16))
    if not minimal and cfg.get("show_tags", True) and tags_text:
        _elem(tags_text, "tags_color", "tags_font", "tags_font_size", "tags_order", 40,
              bottom_padding=int(cfg.get("tags_bottom_padding") or 0))
    if not minimal and cfg.get("show_episode", True):
        ep = item.get("episode_number")
        total = item.get("episode_total")
        if ep and total and tags_text:
            ep_text = f"Day {ep} of {total} in {tags_text}"
        elif ep and tags_text:
            ep_text = f"{tags_text} · Episode {ep}"
        elif ep and total:
            ep_text = f"Day {ep} of {total}"
        elif ep:
            ep_text = f"Episode {ep}"
        else:
            ep_text = ""
        if ep_text:
            _elem(ep_text, "episode_color", "episode_font", "episode_font_size", "episode_order", 30,
                  bottom_padding=int(cfg.get("episode_bottom_padding") or 0))
    if not minimal and cfg.get("show_handle", True) and handle:
        _elem(handle, "handle_color", "handle_font", "handle_font_size", "handle_order", 28,
              bottom_padding=int(cfg.get("handle_bottom_padding") or 0))

    raw.sort(key=lambda e: e["order"])
    return raw


def _screen_draw_filters(
    raw: list[dict], cfg: dict, start: float, end: float, fade_d: float,
) -> list[str]:
    """Build drawbox(tint)+drawtext filters that are BURNED onto the body video
    inside the [start, end] window. Each text line uses a time-based `alpha`
    expression for a smooth fade in/out — single continuous stream, so there is no
    second input, no EOF freeze, and no fade-to-black flash. Tint is gated to the
    same window (constant bg_opacity).
    """
    items = _compute_drawtext_items(raw, int(cfg.get("text_padding_h", 40)))
    if not items:
        return []
    enable = f"between(t,{start:.3f},{end:.3f})"
    parts: list[str] = []

    bg_op = float(cfg.get("bg_opacity") or 0.20)
    if bg_op > 0:
        tint = _css_to_ffmpeg_color(cfg.get("bg_color", "#000000"), bg_op)
        parts.append(f"drawbox=x=0:y=0:w=iw:h=ih:color={tint}:t=fill:enable='{enable}'")

    for it in items:
        tc = _css_to_ffmpeg_color(it["color"])
        t = _escape_drawtext(it["text"])
        fp = it["font_path"].replace("'", "\\'")
        x_expr = f"max({it['padding']}\\,(w-text_w)/2)"
        # Triangular fade: 0→1 over fade_d, hold at 1 (clipped), 1→0 over fade_d.
        # Single-quoted in the filter so the commas/parens are protected.
        alpha = ""
        if fade_d > 0:
            a = (f"clip(min((t-{start:.3f})/{fade_d:.3f},"
                 f"({end:.3f}-t)/{fade_d:.3f}),0,1)")
            alpha = f":alpha='{a}'"
        parts.append(
            f"drawtext=fontfile='{fp}':text='{t}':fontsize={it['font_size']}:fontcolor={tc}"
            f":x={x_expr}:y={it['y']}:shadowcolor=black@0.4:shadowx=2:shadowy=2"
            f"{alpha}:enable='{enable}'"
        )
    return parts


def burn_screens(
    item: dict, icfg: dict, ccfg: dict, body: str, out_dir: Path | None = None,
) -> str:
    """Burn GENERATED intro/cast text + tint directly onto the body video in one
    FFmpeg pass. The body is the only video stream, so its length is unchanged and
    it never freezes or flashes. Asset-mode screens are handled by render_screens.
    Returns the new path, or the body unchanged if nothing was burned/failed.
    """
    intro_gen = icfg.get("enabled", False) and icfg.get("mode", "generated") != "asset"
    cast_gen = ccfg.get("enabled", False) and ccfg.get("mode", "generated") != "asset"
    if not intro_gen and not cast_gen:
        return body

    body_dur = _get_duration(body) or 0.0
    vf: list[str] = []

    if intro_gen:
        raw = _collect_intro_elements(item, icfg)
        if raw:
            d = max(0.5, float(icfg.get("duration_s", 1.5)))
            fd = min(0.5, d / 3) if icfg.get("animation", "fade") != "none" else 0.0
            vf += _screen_draw_filters(raw, icfg, 0.0, d, fd)

    if cast_gen:
        if body_dur <= 0.0:
            log.warning("burn_screens: could not probe body duration — skipping cast burn")
        else:
            raw = _collect_cast_elements(item, ccfg)
            if raw:
                cd = max(0.5, float(ccfg.get("duration_s", 1.5)))
                cs = max(0.0, body_dur - cd)
                fd = min(0.5, cd / 3) if ccfg.get("animation", "fade") != "none" else 0.0
                vf += _screen_draw_filters(raw, ccfg, cs, body_dur, fd)

    if not vf:
        return body

    body_path = Path(body)
    out = str((out_dir or body_path.parent) / f"{body_path.stem}_final.mp4")
    cmd = [
        "ffmpeg", "-hide_banner",
        "-i", body,
        "-vf", ",".join(vf),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-y", out,
    ]
    with _RENDER_SEM:
        ok = _run(cmd, "burn_screens")
    if ok:
        log.info("burn_screens: intro=%s cast=%s → %s", intro_gen, cast_gen, out)
        return out
    log.error("burn_screens: failed — returning body without screens")
    return body


def render_screens(
    item: dict, icfg: dict, ccfg: dict, body: str, out_dir: Path | None = None,
) -> str:
    """Apply intro/cast screens to the body reel. Generated screens are burned
    onto the body (no freeze/flash); asset-mode splash files use the clip-overlay
    path. Returns the final reel path (== body if nothing applied)."""
    out = burn_screens(item, icfg, ccfg, body, out_dir=out_dir)

    intro_asset = icfg.get("enabled", False) and icfg.get("mode", "generated") == "asset"
    cast_asset = ccfg.get("enabled", False) and ccfg.get("mode", "generated") == "asset"
    if intro_asset or cast_asset:
        tmp_dir = out_dir or Path(body).parent
        intro_clip = build_intro_clip(item, icfg, tmp_dir) if intro_asset else None
        cast_clip = build_cast_clip(item, ccfg, tmp_dir) if cast_asset else None
        if intro_clip or cast_clip:
            ov = overlay_screens(
                intro_clip, out, cast_clip,
                intro_duration_s=float(icfg.get("duration_s", 2.0)) if intro_clip else 0.0,
                outro_duration_s=float(ccfg.get("duration_s", 2.5)) if cast_clip else 0.0,
                out_dir=out_dir,
            )
            for tmp in (intro_clip, cast_clip):
                if tmp and tmp != ov:
                    try:
                        Path(tmp).unlink(missing_ok=True)
                    except OSError:
                        pass
            # Drop the burn intermediate if overlay produced a new file.
            if ov != out and out != body:
                try:
                    Path(out).unlink(missing_ok=True)
                except OSError:
                    pass
            out = ov
    return out


def _track_screen_asset_usage(asset_type: str, filename: str) -> None:
    """Best-effort usage_count bump on the matching `assets` row (type=intro
    or type=outro), matched by filename — one list_assets call per
    build_intro_clip()/build_cast_clip() invocation (once per reel, never
    per-frame). Never raises; purely analytics, must never fail a render."""
    try:
        from backend.db import list_assets, increment_asset_usage
        row = next((r for r in list_assets(asset_type) if r.get("filename") == filename), None)
        if row and row.get("id"):
            increment_asset_usage(row["id"])
    except Exception as exc:
        log.debug("screens: %s usage tracking skipped (non-fatal): %s", asset_type, exc)


def build_intro_clip(item: dict, cfg: dict, tmp_dir: Path) -> str | None:
    """Build the intro (splash) screen clip.

    Args:
        item: media row dict (category, tags, etc.).
        cfg:  the 'intro' settings group dict.
        tmp_dir: directory to write temp files into.

    Returns path to a 1080x1920 H.264/AAC clip, or None if disabled/failed.
    """
    if not cfg.get("enabled", False):
        return None

    uid = uuid.uuid4().hex[:8]
    out = str(tmp_dir / f"_intro_{uid}.mov")   # .mov/qtrle so the overlay keeps its alpha
    d = float(cfg.get("duration_s", 1.5))
    mode = cfg.get("mode", "generated")
    animation = cfg.get("animation", "fade")

    if mode == "asset":
        from backend.config import INTRO_DIR
        asset_file = (cfg.get("asset_file") or "").strip()
        if not asset_file:
            log.warning("intro: asset mode but no asset_file set — skipping intro")
            return None
        src = str(INTRO_DIR / asset_file)
        if not Path(src).exists():
            log.warning("intro: asset file not found: %s — skipping intro", src)
            return None
        if not _normalize_asset(src, out, d):
            return None
        _track_screen_asset_usage("intro", asset_file)
        return out

    # Generated mode — collect text elements (shared with the burn path).
    raw = _collect_intro_elements(item, cfg)
    if not raw:
        log.info("intro: no text elements to render — skipping intro")
        return None

    # Transparent overlay so the LIVE, moving reel shows through under the text for
    # the whole intro window (no frozen still, no added duration).
    ok = _build_transparent_clip(
        output_path=out,
        duration_s=d,
        bg_color=cfg.get("bg_color", "#000000"),
        bg_opacity=float(cfg.get("bg_opacity") or 0.20),
        text_padding_h=int(cfg.get("text_padding_h", 40)),
        elements=raw,
        animation=animation,
    )

    return out if ok else None


def build_cast_clip(item: dict, cfg: dict, tmp_dir: Path) -> str | None:
    """Build the cast (outro) screen clip.

    Args:
        item: media row dict.
        cfg:  the 'cast' settings group dict.
        tmp_dir: directory to write temp files into.

    Returns path to a 1080x1920 H.264/AAC clip, or None if disabled/failed.
    """
    if not cfg.get("enabled", False):
        return None

    uid = uuid.uuid4().hex[:8]
    out = str(tmp_dir / f"_cast_{uid}.mov")   # .mov/qtrle so the overlay keeps its alpha
    d = float(cfg.get("duration_s", 1.5))
    mode = cfg.get("mode", "generated")
    animation = cfg.get("animation", "fade")

    if mode == "asset":
        from backend.config import OUTRO_DIR
        asset_file = (cfg.get("asset_file") or "").strip()
        if not asset_file:
            log.warning("cast: asset mode but no asset_file set — skipping cast")
            return None
        src = str(OUTRO_DIR / asset_file)
        if not Path(src).exists():
            log.warning("cast: asset file not found: %s — skipping cast", src)
            return None
        if not _normalize_asset(src, out, d):
            return None
        _track_screen_asset_usage("outro", asset_file)
        return out

    # Generated mode — collect text elements (shared with the burn path).
    raw = _collect_cast_elements(item, cfg)
    if not raw:
        log.info("cast: no text elements to render — skipping cast")
        return None

    # Transparent overlay so the LIVE, moving reel shows through under the cast
    # text over the final seconds (no frozen still, no added duration).
    ok = _build_transparent_clip(
        output_path=out,
        duration_s=d,
        bg_color=cfg.get("bg_color", "#000000"),
        bg_opacity=float(cfg.get("bg_opacity") or 0.20),
        text_padding_h=int(cfg.get("text_padding_h", 40)),
        elements=raw,
        animation=animation,
    )

    return out if ok else None


def _get_duration(path: str) -> float | None:
    """Return video duration in seconds via ffprobe, or None on failure.

    Uses format-level duration (container header) rather than stream-level so
    this works reliably for libx264 MP4s where stream=duration can be 'N/A'.
    """
    result = subprocess.run(
        ["ffprobe", "-hide_banner", "-loglevel", "error",
         "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return None


def overlay_screens(
    intro: str | None,
    body: str,
    outro: str | None,
    intro_duration_s: float = 2.0,
    outro_duration_s: float = 2.5,
    intro_animation: str = "fade",
    cast_animation: str = "fade",
    out_dir: Path | None = None,
) -> str:
    """Composite intro/cast clips on top of body video via FFmpeg overlay.

    Body plays from second 0. Intro overlays on top for the first
    intro_duration_s seconds; cast overlays the final outro_duration_s seconds.
    Total video length equals the body duration — no extra time added.

    The intro/cast clips are transparent alpha cards with their fade baked in
    (built by _build_transparent_clip), so they composite straight over the live
    body video. intro_animation/cast_animation are kept for signature compat but
    are no longer used here. Falls back to the body path if both overlay clips are
    absent or FFmpeg fails.
    """
    if not intro and not outro:
        return body

    body_path = Path(body)
    out_dir = out_dir or body_path.parent
    out = str(out_dir / f"{body_path.stem}_final.mp4")

    # Probe body duration up-front; used both for cast_start calc and the -t
    # output clamp that guarantees output length == body length regardless of
    # how long any overlay clip turns out to be.
    body_dur = _get_duration(body) or 0.0
    if body_dur == 0.0:
        log.warning("overlay_screens: could not probe body duration — output will not be duration-clamped")

    # Build ordered FFmpeg inputs; track -i index for filter references.
    cmd_pre: list[str] = []
    body_idx = 0
    cmd_pre += ["-i", body]
    next_idx = 1

    intro_idx: int | None = None
    if intro:
        intro_idx = next_idx
        cmd_pre += ["-i", intro]
        next_idx += 1

    outro_idx: int | None = None
    cast_start = 0.0
    if outro:
        cast_start = max(0.0, body_dur - outro_duration_s)
        if cast_start == 0.0 and body_dur > 0.0:
            log.warning("overlay_screens: body (%gs) shorter than cast (%gs) — cast covers full video",
                        body_dur, outro_duration_s)
        cmd_pre += ["-i", outro]
        outro_idx = next_idx
        next_idx += 1  # noqa: F841

    # Chain overlay filters sequentially. The intro/cast clips are transparent
    # (alpha) cards with their fade baked in, so we overlay them straight onto the
    # body — the live video plays through underneath. eof_action=pass lets the body
    # show once the overlay clip ends.
    filter_parts: list[str] = []
    current = f"{body_idx}:v"

    if intro_idx is not None:
        d = intro_duration_s
        filter_parts.append(
            f"[{current}][{intro_idx}:v]overlay=0:0:eof_action=pass:enable='lte(t,{d:.3f})'[v_intro]"
        )
        current = "v_intro"

    if outro_idx is not None:
        # setpts positions the cast clip at cast_start on the output timeline; the
        # clip's own fade is already baked relative to its start.
        filter_parts.append(f"[{outro_idx}:v]setpts=PTS+{cast_start:.3f}/TB[outro_delayed]")
        filter_parts.append(
            f"[{current}][outro_delayed]overlay=0:0:eof_action=pass:enable='gte(t,{cast_start:.3f})'[v_cast]"
        )
        current = "v_cast"

    fc = ";".join(filter_parts)

    duration_args = ["-t", f"{body_dur:.6f}"] if body_dur > 0 else []
    cmd = ["ffmpeg", "-hide_banner"] + cmd_pre + [
        "-filter_complex", fc,
        "-map", f"[{current}]",
        "-map", f"{body_idx}:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
    ] + duration_args + [
        "-y", out,
    ]

    if _run(cmd, "overlay_screens"):
        log.info("overlay_screens: intro=%s cast=%s → %s", bool(intro), bool(outro), out)
        return out

    log.error("overlay_screens: failed — returning body without screens")
    return body


def concat_screens(
    intro: str | None,
    body: str,
    outro: str | None,
    out_dir: Path | None = None,
) -> str:
    """Concatenate intro + body + outro into a single clip.

    Uses filter_complex concat (not the concat demuxer) for robustness
    against minor parameter differences between clips. Each input is
    normalized to 1080x1920/30fps/SAR=1 before concat.

    Args:
        intro: path to intro clip, or None to skip.
        body:  path to body reel (required).
        outro: path to outro clip, or None to skip.
        out_dir: directory for output; defaults to body's parent.

    Returns output path (may equal body if no intro/outro).
    """
    segments = [s for s in [intro, body, outro] if s]
    n = len(segments)
    if n == 1:
        return body

    body_path = Path(body)
    out_dir = out_dir or body_path.parent
    out = str(out_dir / f"{body_path.stem}_final.mp4")

    norm_filter = (
        f"scale={_W}:{_H}:force_original_aspect_ratio=decrease,"
        f"pad={_W}:{_H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={_FPS}"
    )
    fc_parts: list[str] = []
    for i in range(n):
        fc_parts.append(f"[{i}:v]{norm_filter}[v{i}]")

    vid_chain = "".join(f"[v{i}]" for i in range(n))
    aud_chain = "".join(f"[{i}:a]" for i in range(n))
    fc_parts.append(f"{vid_chain}concat=n={n}:v=1:a=0[vout]")
    fc_parts.append(f"{aud_chain}concat=n={n}:v=0:a=1[aout]")
    fc = ";".join(fc_parts)

    cmd = ["ffmpeg", "-hide_banner"]
    for seg in segments:
        cmd.extend(["-i", seg])
    cmd.extend([
        "-filter_complex", fc,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-y", out,
    ])

    if _run(cmd, f"concat_screens(n={n})"):
        log.info("concat_screens: %d segments → %s", n, out)
        return out

    log.error("concat_screens: failed — returning body without screens")
    return body
