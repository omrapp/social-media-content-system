"""editor_layers — text overlay filter construction (v2.0.0 Phase 3).

The security-relevant assertion here is that user content NEVER appears in the
filter string: it only ever reaches ffmpeg through `textfile=`. Everything else
(position maths, enable window, fade) is parity with the browser preview.
"""

import pytest

from backend.pipeline import editor_layers as el


def _layer(**over):
    base = {
        "id": "t1",
        "content": "Hello",
        "font": "",
        "font_path": None,
        "size": 64,
        "color": "#ffffff",
        "x": 0.5,
        "y": 0.5,
        "anchor": "center",
        "start_s": 0.0,
        "end_s": 0.0,
        "animation": "fade",
    }
    base.update(over)
    return base


def _build(layer, media_id="test_layers"):
    files = el.write_text_files(media_id, [layer])
    return el.build_text_filters([layer], files), files


def test_hostile_content_never_enters_the_filtergraph():
    nasty = "a:b'c%d\\e,f\nsecond line"
    layer = _layer(content=nasty)
    filters, files = _build(layer, media_id="test_layers_hostile")
    assert len(filters) == 1
    for fragment in (nasty, "a:b", "second line"):
        assert fragment not in filters[0]
    # ...but it does reach the file drawtext reads, byte for byte.
    assert open(files["t1"], encoding="utf-8").read() == nasty


def test_textfile_and_reload_are_used_not_text():
    filters, _ = _build(_layer())
    f = filters[0]
    assert f.startswith("drawtext=")
    assert "textfile='" in f
    assert ":text=" not in f
    assert "reload=0" in f


def test_enable_window_open_ended_when_end_not_after_start():
    open_ended, _ = _build(_layer(start_s=2.0, end_s=0.0))
    bounded, _ = _build(_layer(start_s=2.0, end_s=5.0))
    assert "enable='gte(t\\,2.000)'" in open_ended[0]
    assert "enable='between(t\\,2.000\\,5.000)'" in bounded[0]


@pytest.mark.parametrize("anchor,expected", [
    ("left", "x=540.0:"),
    ("center", "x=540.0-text_w/2:"),
    ("right", "x=540.0-text_w:"),
])
def test_anchor_drives_the_x_expression(anchor, expected):
    filters, _ = _build(_layer(anchor=anchor, x=0.5))
    assert expected in filters[0]


def test_y_is_always_centred_on_the_normalized_position():
    filters, _ = _build(_layer(y=0.25))
    # 0.25 * 1920 = 480; the preview centres the box the same way.
    assert "y=480.0-text_h/2" in filters[0]


def test_colour_is_rgb_not_bgr():
    filters, _ = _build(_layer(color="#ff0000", animation="none"))
    assert "fontcolor=0xff0000" in filters[0]


def test_fade_animation_emits_an_alpha_ramp():
    faded, _ = _build(_layer(animation="fade", start_s=1.0, end_s=4.0))
    plain, _ = _build(_layer(animation="none", start_s=1.0, end_s=4.0))
    assert "alpha='" in faded[0]
    assert "alpha='" not in plain[0]


def test_empty_content_is_skipped_rather_than_written():
    files = el.write_text_files("test_layers_empty", [_layer(content="   ")])
    assert files == {}
    assert el.build_text_filters([_layer(content="   ")], files) == []


def test_layer_without_a_textfile_is_dropped_not_inlined():
    # A layer whose file write was skipped must not fall back to text=.
    assert el.build_text_filters([_layer()], {}) == []
