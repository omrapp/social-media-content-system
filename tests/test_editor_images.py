"""Phase 5 (image/sticker layers) contract tests — no FFmpeg, no DB.

Two very different failure modes are covered here:

  * `build_image_filters` producing a chain that looks fine but positions the
    sticker somewhere the browser preview never showed it (the overlay x/y
    convention is a parity contract with ReelComposition.tsx);
  * and the dangerous one — `_build_cmd` hardcodes the music bed as `[1:a]` and
    derives `voiceover_idx` from `len(audio_inputs)`, so an image input inserted
    anywhere but LAST silently re-points the audio graph of every reel. Plan
    §10E asks for the full {audio combos} × {0,1,3 images} matrix; that is
    `test_image_inputs_come_last` below, plus an argv-equality regression that
    pins the zero-image output byte for byte.
"""

from __future__ import annotations

import re

import pytest

from backend.pipeline import editor_layers as el
from backend.pipeline.video_edit import VideoEditor


# ── build_image_filters ──────────────────────────────────────────────────────

def _img(**over):
    base = {
        "id": "i1", "asset": "stickers/logo.png", "asset_path": "/x/logo.png",
        "x": 0.5, "y": 0.5, "w": None, "h": None,
        "start_s": 0.0, "end_s": 0.0, "opacity": 1.0, "z": 0,
    }
    base.update(over)
    return base


def test_no_layers_is_a_passthrough():
    assert el.build_image_filters([], 2, "[vout]") == ([], "[vout]")


def test_scale_is_omitted_when_neither_dimension_is_set():
    frags, _ = el.build_image_filters([_img()], 1, "[0:v]")
    assert frags[0] == "[1:v]format=rgba[eimg0]"


@pytest.mark.parametrize("dims,expected", [
    ({"w": 0.25}, "scale=270:-1"),          # -1 = keep aspect, like CSS height:auto
    ({"h": 0.10}, "scale=-1:192"),
    ({"w": 0.25, "h": 0.10}, "scale=270:192"),
])
def test_scale_variants(dims, expected):
    frags, _ = el.build_image_filters([_img(**dims)], 1, "[0:v]")
    assert frags[0] == f"[1:v]format=rgba,{expected}[eimg0]"


def test_opacity_below_one_emits_an_alpha_mixer():
    frags, _ = el.build_image_filters([_img(opacity=0.4)], 1, "[0:v]")
    assert "colorchannelmixer=aa=0.400" in frags[0]


def test_full_opacity_costs_no_extra_filter():
    frags, _ = el.build_image_filters([_img(opacity=1.0)], 1, "[0:v]")
    assert "colorchannelmixer" not in frags[0]


def test_position_uses_overlay_vars_not_baked_pixels():
    # Centre convention: the sticker's own w/h is subtracted, which is what
    # `translate(-50%,-50%)` does in the preview.
    frags, _ = el.build_image_filters([_img(x=0.25, y=0.75)], 1, "[0:v]")
    assert "overlay=x=0.2500*W-w/2:y=0.7500*H-h/2" in frags[1]


def test_enable_window_open_ended_vs_bounded():
    open_ended, _ = el.build_image_filters([_img(start_s=2.0, end_s=0.0)], 1, "[0:v]")
    bounded, _ = el.build_image_filters([_img(start_s=2.0, end_s=5.0)], 1, "[0:v]")
    assert "enable='gte(t\\,2.000)'" in open_ended[1]
    assert "enable='between(t\\,2.000\\,5.000)'" in bounded[1]


def test_single_frame_stickers_persist_for_the_whole_window():
    frags, _ = el.build_image_filters([_img()], 1, "[0:v]")
    assert "eof_action=repeat" in frags[1]


def test_labels_chain_across_layers():
    layers = [_img(id="a"), _img(id="b"), _img(id="c")]
    frags, final = el.build_image_filters(layers, 2, "[vout]")
    assert len(frags) == 6                      # one prep + one overlay each
    assert frags[1].startswith("[vout][eimg0]overlay=")
    assert frags[3].startswith("[evid0][eimg1]overlay=")
    assert frags[5].startswith("[evid1][eimg2]overlay=")
    assert final == "[evid2]"
    # Input indices advance with the layer, matching the -i order _build_cmd
    # appends them in.
    assert frags[0].startswith("[2:v]")
    assert frags[2].startswith("[3:v]")
    assert frags[4].startswith("[4:v]")


def test_given_order_is_preserved_because_compile_already_z_sorted():
    # build_image_filters must NOT re-sort: compile() owns z ordering, and the
    # input indices are already assigned against that order.
    layers = [_img(id="top", z=9, x=0.1), _img(id="bottom", z=0, x=0.9)]
    frags, _ = el.build_image_filters(layers, 1, "[0:v]")
    assert "x=0.1000*W" in frags[1]             # first given == first composited
    assert "x=0.9000*W" in frags[3]


def test_out_of_range_numbers_are_clamped_before_formatting():
    frags, _ = el.build_image_filters([_img(x=9.0, y=-3.0, opacity=5.0)], 1, "[0:v]")
    assert "overlay=x=1.0000*W-w/2:y=0.0000*H-h/2" in frags[1]
    assert "colorchannelmixer" not in frags[0]  # clamped to 1.0 ⇒ no mixer


# ── _build_cmd input order (plan §10E) ───────────────────────────────────────

IN = "/tmp/reel.mp4"
OUT = "/tmp/out.mp4"
MUSIC = "/tmp/bed.m4a"
VO = "/tmp/vo.mp3"


@pytest.fixture(autouse=True)
def _no_probes(monkeypatch):
    """Pin the two subprocess-backed lookups _build_cmd makes, so the argv is a
    pure function of the builder state."""
    monkeypatch.setattr(VideoEditor, "_get_duration", lambda self: 10.0)
    monkeypatch.setattr("backend.pipeline.video_edit.best_audio_offset",
                        lambda path, seg_len: 0.0)


def _editor(audio: str, images: int, with_filters: bool = True) -> VideoEditor:
    ed = VideoEditor(IN)
    if with_filters:
        ed.filters.append("scale=1080:1920")
    if audio in ("music", "both"):
        ed.add_background_music(MUSIC, volume=0.15)
    if audio in ("voiceover", "both"):
        ed.add_voiceover(VO)
    for i in range(images):
        ed.add_image_overlay(f"/tmp/s{i}.png", x=0.5, y=0.5)
    return ed


def _inputs(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "-i"]


def _voiceover_label(cmd: list[str]) -> str | None:
    """The `[N:a]` the voiceover amix reads from — the number that must not move
    when image inputs are added."""
    if "-filter_complex" not in cmd:
        return None
    graph = cmd[cmd.index("-filter_complex") + 1]
    for frag in graph.split(";"):
        if frag.endswith("[aout]") and "amix" in frag:
            m = re.search(r"\[(\d+):a\]amix", frag)
            if m:
                return f"[{m.group(1)}:a]"
    return None


@pytest.mark.parametrize("audio", ["none", "music", "voiceover", "both"])
@pytest.mark.parametrize("images", [0, 1, 3])
def test_image_inputs_come_last(audio, images):
    cmd = _editor(audio, images)._build_cmd(OUT, 20, "medium")
    ins = _inputs(cmd)

    assert ins[0] == IN
    assert len(ins) == 1 + (audio in ("music", "both")) + \
        (audio in ("voiceover", "both")) + images

    stickers = [f"/tmp/s{i}.png" for i in range(images)]
    assert ins[len(ins) - images:] == stickers          # …and in layer order
    for a in (MUSIC, VO):
        if a in ins:
            assert all(ins.index(a) < ins.index(s) for s in stickers)


@pytest.mark.parametrize("audio", ["music", "both"])
@pytest.mark.parametrize("images", [0, 1, 3])
def test_music_bed_is_always_input_one(audio, images):
    cmd = _editor(audio, images)._build_cmd(OUT, 20, "medium")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "[1:a]" in graph


@pytest.mark.parametrize("audio", ["voiceover", "both"])
def test_voiceover_index_is_unchanged_by_images(audio):
    labels = {
        n: _voiceover_label(_editor(audio, n)._build_cmd(OUT, 20, "medium"))
        for n in (0, 1, 3)
    }
    expected = "[2:a]" if audio == "both" else "[1:a]"
    assert set(labels.values()) == {expected}


# ── the no-audio + images path ───────────────────────────────────────────────

def test_images_without_audio_map_explicitly():
    # filter_complex disables ffmpeg's default stream selection, so an unmapped
    # filter output aborts the render. `0:a?` keeps a silent source working.
    cmd = _editor("none", 2)._build_cmd(OUT, 20, "medium")
    assert "-vf" not in cmd
    maps = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "-map"]
    assert maps == ["[evid1]", "0:a?"]
    assert "-shortest" not in cmd


def test_images_without_filters_chain_straight_off_the_source():
    cmd = _editor("none", 1, with_filters=False)._build_cmd(OUT, 20, "medium")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph.split(";")[1].startswith("[0:v][eimg0]overlay=")


def test_images_with_audio_map_the_overlay_output():
    cmd = _editor("music", 1)._build_cmd(OUT, 20, "medium")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph.startswith("[0:v]scale=1080:1920[evfx];")
    maps = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "-map"]
    assert maps == ["[evid0]", "[aout]"]


# ── argv regression: zero images must be byte-identical to pre-Phase-5 ────────

_TAIL = [
    "-c:v", "libx264", "-preset", "fast", "-crf", "22",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart",
    "-y", OUT,
]


def test_argv_unchanged_no_audio():
    cmd = _editor("none", 0)._build_cmd(OUT, 22, "fast")
    assert cmd == ["ffmpeg", "-hide_banner", "-i", IN,
                   "-vf", "scale=1080:1920"] + _TAIL


def test_argv_unchanged_music():
    cmd = _editor("music", 0)._build_cmd(OUT, 22, "fast")
    assert cmd == [
        "ffmpeg", "-hide_banner", "-i", IN,
        "-stream_loop", "-1", "-i", MUSIC,
        "-filter_complex",
        "[0:v]scale=1080:1920[vout];"
        "[1:a]volume=0.15,afade=t=out:st=8.0:d=2[amusic];"
        "[0:a][amusic]amix=inputs=2:duration=first[aout]",
        "-map", "[vout]", "-map", "[aout]",
    ] + _TAIL


def test_argv_unchanged_voiceover():
    cmd = _editor("voiceover", 0)._build_cmd(OUT, 22, "fast")
    assert cmd == [
        "ffmpeg", "-hide_banner", "-i", IN,
        "-i", VO,
        "-filter_complex",
        "[0:v]scale=1080:1920[vout];"
        "[0:a]volume=0.08[abed];"
        "[abed][1:a]amix=inputs=2:duration=first[aout]",
        "-map", "[vout]", "-map", "[aout]", "-shortest",
    ] + _TAIL
