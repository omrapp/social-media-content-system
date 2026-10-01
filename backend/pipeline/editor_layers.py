"""Editor overlay layers → FFmpeg filters (v2.0.0 Phase 3 / Phase 5).

Text is rendered with drawtext's `textfile=` option, never `text=`. That is the
whole security argument of this module: user-authored strings never enter the
filtergraph, so `:`, `'`, `%`, `\\`, `,` and newlines are structurally harmless
rather than escape-dependent. Only the FILE PATH is escaped, and we author that
path ourselves.

The textfiles are written under `EDITOR_DIR/<media_id>/layers/` and deliberately
outlive the ffmpeg process (`reload=0` means ffmpeg reads each file once at
filter init, but the file must still exist for the whole run, and keeping them
afterwards makes a failed render debuggable).

Image/sticker layers (Phase 5) have no such problem: the asset is an ffmpeg
`-i` argv entry, so its path never reaches a filtergraph at all. What they do
cost is one extra decoded input each, which is why build_image_filters takes an
input index and why video_edit appends those inputs LAST (see plan risk #6).

Coordinates arrive NORMALIZED 0–1 from the EDL so the browser preview and the
render agree without a scale factor; they are multiplied by the canvas here.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.config import EDITOR_DIR, FONTS_DIR

log = logging.getLogger(__name__)

# Fade-in/out length for animation="fade". Matches the CSS transition the editor
# preview uses, so what the user sees is what gets burned in.
FADE_S = 0.3

_DEFAULT_FONTS = (
    "PlayfairDisplay-SemiBold.ttf",
    # Bind-mounts can shadow /app/assets at runtime; this one ships in the image.
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def _escape_path(value: str) -> str:
    """Escape a path for a single-quoted ffmpeg filter option value. Same order
    as video_edit._escape_filter_value: backslash first, then the specials."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )


def _hex_to_ffmpeg(color: str) -> str:
    """'#RRGGBB' → '0xRRGGBB'. drawtext takes RGB in that order (unlike ASS,
    which is BGR — see video_edit._ass_color)."""
    h = (color or "#ffffff").lstrip("#")
    if len(h) != 6:
        h = "ffffff"
    return f"0x{h.lower()}"


def _clamp01(value, default: float = 0.0) -> float:
    """Clamp a normalized 0–1 EDL number, falling back to *default* on anything
    non-numeric. Everything that reaches a filter string goes through here first
    (§8.1): pydantic already bounds these fields, but the renderer must not
    depend on that — a hand-built dict has to be equally harmless."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _default_font() -> str | None:
    for cand in _DEFAULT_FONTS:
        p = Path(cand) if Path(cand).is_absolute() else FONTS_DIR / cand
        if p.exists():
            return str(p)
    return None


def layer_dir(media_id: str) -> Path:
    """Per-reel scratch dir for layer textfiles. Under EDITOR_DIR, which is a
    sibling of MERGE_DIR precisely so merge cleanup's rmtree can never reach it."""
    d = EDITOR_DIR / str(media_id) / "layers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_text_files(media_id: str, text_layers: list[dict]) -> dict[str, str]:
    """Write one UTF-8 textfile per text layer. Returns {layer_id: path}.

    Layers whose content is empty are skipped — an empty textfile makes drawtext
    error out, and compile() already rejects them, so reaching here means a
    caller bypassed validation.
    """
    out: dict[str, str] = {}
    if not text_layers:
        return out
    d = layer_dir(media_id)
    for i, layer in enumerate(text_layers):
        content = str(layer.get("content") or "")
        if not content.strip():
            log.warning("editor_layers: text layer %s has empty content — skipped",
                        layer.get("id"))
            continue
        # Filename is ours, not the user's: the layer id is validated upstream,
        # but the index keeps the name unique even if two ids collide.
        path = d / f"text_{i:02d}.txt"
        path.write_text(content, encoding="utf-8")
        out[str(layer.get("id") or i)] = str(path)
    return out


def _enable_expr(start_s: float, end_s: float) -> str:
    """`enable=` window. end <= start means "until the end of the reel" — the
    editor writes that when a layer is dragged past the last cut."""
    if end_s > start_s:
        return f"between(t\\,{start_s:.3f}\\,{end_s:.3f})"
    return f"gte(t\\,{start_s:.3f})"


def _alpha_expr(start_s: float, end_s: float) -> str:
    """Piecewise fade in/out. Written as an expression rather than two extra
    filters so a text layer stays exactly one drawtext."""
    f = FADE_S
    fin = f"min(1\\,(t-{start_s:.3f})/{f})"
    if end_s > start_s:
        fout = f"min(1\\,({end_s:.3f}-t)/{f})"
        return f"max(0\\,min({fin}\\,{fout}))"
    return f"max(0\\,{fin})"


def _position_exprs(layer: dict, w: int, h: int) -> tuple[str, str]:
    """Normalized x/y + anchor → drawtext x/y expressions.

    y always centres the text box on the normalized y, which is what the browser
    preview does with `translate(-50%)`; x depends on the anchor so a left-anchored
    caption stays put when its text changes length.
    """
    px = float(layer.get("x", 0.5)) * w
    py = float(layer.get("y", 0.5)) * h
    anchor = str(layer.get("anchor") or "center")
    if anchor == "left":
        x_expr = f"{px:.1f}"
    elif anchor == "right":
        x_expr = f"{px:.1f}-text_w"
    else:
        x_expr = f"{px:.1f}-text_w/2"
    return x_expr, f"{py:.1f}-text_h/2"


def build_text_filters(text_layers: list[dict], files: dict[str, str],
                       canvas_w: int = 1080, canvas_h: int = 1920) -> list[str]:
    """One drawtext filter per text layer, in document order (later = on top).

    `files` comes from write_text_files. A layer with no textfile is skipped
    rather than falling back to `text=` — falling back would put user content
    into the filtergraph, which is exactly what this module exists to prevent.
    """
    filters: list[str] = []
    fallback_font = _default_font()

    for layer in text_layers or []:
        lid = str(layer.get("id") or "")
        textfile = files.get(lid)
        if not textfile:
            continue
        # compile() resolved and containment-checked this; "" means "use default".
        font_path = layer.get("font_path") or fallback_font
        if not font_path:
            log.warning("editor_layers: no font available — text layer %s skipped", lid)
            continue

        start_s = max(0.0, float(layer.get("start_s") or 0.0))
        end_s = float(layer.get("end_s") or 0.0)
        x_expr, y_expr = _position_exprs(layer, canvas_w, canvas_h)
        color = _hex_to_ffmpeg(str(layer.get("color") or "#ffffff"))
        size = int(layer.get("size") or 64)

        parts = [
            f"textfile='{_escape_path(textfile)}'",
            f"fontfile='{_escape_path(font_path)}'",
            f"fontsize={size}",
            f"x={x_expr}",
            f"y={y_expr}",
            f"enable='{_enable_expr(start_s, end_s)}'",
            # reload=0: ffmpeg reads the file once at init. Set explicitly because
            # the default changed across ffmpeg versions.
            "reload=0",
            # Thin shadow so light text stays readable over bright footage; the
            # preview draws the same shadow.
            "shadowcolor=black@0.5", "shadowx=2", "shadowy=2",
        ]
        if str(layer.get("animation") or "fade") == "fade":
            parts.append(f"fontcolor={color}@1")
            parts.append(f"alpha='{_alpha_expr(start_s, end_s)}'")
        else:
            parts.append(f"fontcolor={color}")

        filters.append("drawtext=" + ":".join(parts))

    return filters


def build_image_filters(image_layers: list[dict], first_input_idx: int,
                        base_label: str, canvas_w: int = 1080,
                        canvas_h: int = 1920) -> tuple[list[str], str]:
    """Image/sticker layers → filter_complex fragments + the final video label.

    Unlike text, an image cannot be a `-vf` filter: it needs a second decoded
    stream, so each layer is one extra ffmpeg `-i` and one `overlay`. That is
    also why images are the SAFE layer type — the asset path travels as argv,
    never through the filtergraph, so no escaping question exists for it. Only
    numbers (already clamped + `%`-formatted below) are interpolated.

    `image_layers` arrive z-sorted from compile(); layer i consumes input
    `first_input_idx + i`, so the caller must have appended those `-i` in the
    same order. Empty input is a passthrough — (no fragments, base_label
    unchanged) — so the caller's chain is untouched when there are no stickers.
    """
    if not image_layers:
        return [], base_label

    frags: list[str] = []
    cur = base_label
    for i, layer in enumerate(image_layers):
        idx = first_input_idx + i

        # Prep: rgba first (a jpg-ish input has no alpha plane to mix into),
        # then optional scale, then optional constant-alpha.
        w = layer.get("w")
        h = layer.get("h")
        # A sub-pixel fraction would round to "scale=0", which ffmpeg rejects
        # outright — floor at one pixel so a fat-fingered size degrades to an
        # invisible sticker instead of a failed render.
        wp = max(1.0, _clamp01(w) * canvas_w) if w is not None else None
        hp = max(1.0, _clamp01(h) * canvas_h) if h is not None else None
        scale = ""
        if wp is not None and hp is not None:
            scale = f",scale={wp:.0f}:{hp:.0f}"
        elif wp is not None:
            # -1 keeps the source aspect ratio, matching the browser's
            # `width: X%; height: auto`.
            scale = f",scale={wp:.0f}:-1"
        elif hp is not None:
            scale = f",scale=-1:{hp:.0f}"

        opacity = _clamp01(layer.get("opacity", 1.0), 1.0)
        alpha = f",colorchannelmixer=aa={opacity:.3f}" if opacity < 1.0 else ""
        frags.append(f"[{idx}:v]format=rgba{scale}{alpha}[eimg{i}]")

        # Composite. x/y are the NORMALIZED CENTRE of the sticker, the same
        # convention the text layers use and the same one ReelComposition.tsx
        # renders with `translate(-50%,-50%)`. Expressed with overlay's own
        # W/H (main) and w/h (overlay) vars rather than pre-multiplied pixels,
        # so the result stays correct if the canvas or the scaled sticker size
        # differs from what we assumed here — that is the parity contract.
        x = _clamp01(layer.get("x", 0.5), 0.5)
        y = _clamp01(layer.get("y", 0.5), 0.5)
        start_s = max(0.0, float(layer.get("start_s") or 0.0))
        end_s = float(layer.get("end_s") or 0.0)
        out = f"[evid{i}]"
        frags.append(
            f"{cur}[eimg{i}]overlay=x={x:.4f}*W-w/2:y={y:.4f}*H-h/2:"
            # Reuses the text layers' window helper — its commas are already
            # `\,`-escaped for filter_complex, which is exactly why it is
            # reused rather than re-derived here.
            f"enable='{_enable_expr(start_s, end_s)}':"
            # A PNG is a single frame, so its stream ends immediately; without
            # eof_action=repeat the overlay would vanish after frame one. Set
            # explicitly because ffmpeg's default has moved across versions.
            f"eof_action=repeat{out}"
        )
        cur = out

    return frags, cur
