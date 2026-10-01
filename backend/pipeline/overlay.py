"""
Shared branding overlay helpers used by video_edit (filter chain)
and thumbnail.py (static image overlay).

Pure module — no DB reads, no settings reads. All parameters are
passed in by the caller so the module is trivially testable.
"""


def _escape_drawtext(text: str) -> str:
    """Escape FFmpeg drawtext metacharacters in the correct order.

    Order matters: backslash first (avoids double-escaping our own
    additions), then % (starts %{...} expansion), colon (option
    separator), and single-quote (value delimiter).
    """
    return (
        text.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace(":", "\\:")
            .replace("'", "\\'")
    )


def _css_to_ffmpeg_color(css: str, opacity: float = 1.0) -> str:
    """Convert a CSS hex color (#RRGGBB) to FFmpeg color format.

    FFmpeg accepts 0xRRGGBB with an optional @opacity suffix.
    Named colors (white, black, …) are passed through unchanged.
    """
    css = css.strip()
    if css.startswith("#") and len(css) == 7:
        ffmpeg = "0x" + css[1:].upper()
        return f"{ffmpeg}@{opacity:.2f}" if opacity < 1.0 else ffmpeg
    # Named color — append opacity if needed
    return f"{css}@{opacity:.2f}" if opacity < 1.0 else css


def format_tags(tags) -> str | None:
    """Format a display string for the bottom bar from a clip's tags.

    Accepts a list (Supabase) or a raw string (SQLite fallback stores tags as
    a JSON-text column that isn't parsed everywhere). Returns the tags
    comma-joined, or None when there are none.
    """
    if not tags:
        return None
    if isinstance(tags, str):
        return tags.strip() or None
    cleaned = [str(t).strip() for t in tags if t and str(t).strip()]
    return ", ".join(cleaned) if cleaned else None


def build_branding_filters(
    location: str | None,
    handle: str = "",
    bar_h: int = 45,
    font_path: str = "",
    bar_bg_color: str = "#ffffff",
    text_color: str = "#000000",
    bar_opacity: float = 1.0,
    bar_position: str = "bottom",
    location_side: str = "left",
    handle_side: str = "right",
    custom_text: str = "",
    font_size: int = 0,
) -> list[str]:
    """Build FFmpeg filter strings for the branded bar overlay.

    Layout: full-width bar (top or bottom) with configurable colors,
    opacity, and independent left/right placement for location and handle.
    Optional custom_text renders as a smaller second line below location.

    The returned strings must be appended LAST in the filter chain
    so they composite on top of colour grading and sharpening.

    Returns an empty list when all text fields are empty (nothing to draw).
    """
    handle = (handle or "").strip()
    custom_text = (custom_text or "").strip()
    location = (location or "").strip() or None

    if not handle and not location and not custom_text:
        return []

    has_custom = bool(custom_text)
    font_size = font_size if font_size > 0 else int(bar_h * (0.42 if has_custom else 0.58))
    font_size = min(font_size, bar_h - 2)
    # drawbox uses ih (input height) because its own h parameter shadows the frame h.
    # drawtext uses h which is the frame height in that filter's expression context.
    box_y  = f"ih-{bar_h}" if bar_position == "bottom" else "0"
    text_base_y = f"h-{bar_h}" if bar_position == "bottom" else "0"

    if has_custom:
        text_y = f"{text_base_y}+{max(3, int(bar_h * 0.10))}"
        custom_y = f"{text_base_y}+{int(bar_h * 0.10) + font_size + 3}"
        custom_font_size = int(bar_h * 0.32)
    else:
        text_y = f"{text_base_y}+({bar_h}-text_h)/2"

    ffmpeg_bg = _css_to_ffmpeg_color(bar_bg_color, bar_opacity)
    ffmpeg_text = _css_to_ffmpeg_color(text_color)

    def _x(side: str) -> str:
        return "w-text_w-24" if side == "right" else "24"

    filters: list[str] = []

    # Solid (or semi-transparent) bar.
    filters.append(
        f"drawbox=x=0:y={box_y}:w=iw:h={bar_h}:color={ffmpeg_bg}:t=fill"
    )

    # Location text.
    if location:
        escaped_loc = _escape_drawtext(location)
        filters.append(
            f"drawtext=fontfile='{font_path}':text='{escaped_loc}':"
            f"fontsize={font_size}:fontcolor={ffmpeg_text}:"
            f"x={_x(location_side)}:y={text_y}"
        )

    # Handle text (optional).
    if handle:
        escaped_handle = _escape_drawtext(handle)
        filters.append(
            f"drawtext=fontfile='{font_path}':text='{escaped_handle}':"
            f"fontsize={font_size}:fontcolor={ffmpeg_text}:"
            f"x={_x(handle_side)}:y={text_y}"
        )

    # Custom text — second line below location.
    if custom_text:
        escaped_custom = _escape_drawtext(custom_text)
        filters.append(
            f"drawtext=fontfile='{font_path}':text='{escaped_custom}':"
            f"fontsize={custom_font_size}:fontcolor={ffmpeg_text}:"
            f"x={_x(location_side)}:y={custom_y}"
        )

    return filters
