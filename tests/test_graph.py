from dataclasses import replace
from pathlib import Path

import pytest

from utavideo.graph import RenderSpec, StillSpec, build_args, build_still_args, escape_filter_arg

SPEC = RenderSpec(
    mode="final",
    size=(1920, 1080),
    fps=30,
    duration_s=12.3456,
    audio=Path("/a/mix v1.0.wav"),
    subtitles=Path("/w/final.ass"),
    fontsdir=Path("/c/fonts"),
    background=Path("/a/bg.png"),
)


def _contains(args: list[str], seq: list[str]) -> bool:
    return any(args[i : i + len(seq)] == seq for i in range(len(args) - len(seq) + 1))


def _filter(args: list[str]) -> str:
    return args[args.index("-filter_complex") + 1]


def test_escape_filter_arg() -> None:
    assert escape_filter_arg("/a/it's [x], y:z") == r"/a/it\\\'s \[x\]\, y\\:z"
    plain = "/mnt/d/Videos/20260913 新しい曲"
    assert escape_filter_arg(plain) == plain


def test_final_args() -> None:
    args = build_args(SPEC)
    assert args[0] == "ffmpeg"
    assert _contains(args, ["-loop", "1", "-framerate", "30", "-i", "/a/bg.png"])
    assert _contains(args, ["-i", "/a/mix v1.0.wav"])
    assert _filter(args) == (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1920:1080:(iw-ow)*0.5:(ih-oh)*0.5,"
        "setsar=1,fps=30,format=rgb24,subtitles=filename=/w/final.ass:fontsdir=/c/fonts,"
        "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[v]"
    )
    assert _contains(args, ["-c:v", "libx264", "-preset", "slow", "-crf", "18"])
    assert _contains(args, ["-movflags", "+faststart"])
    assert args[-2:] == ["-t", "12.346"]


def test_animated_background_loops() -> None:
    args = build_args(replace(SPEC, background=Path("/a/bg_loop.gif")))
    assert _contains(args, ["-stream_loop", "-1", "-i", "/a/bg_loop.gif"])


def test_contain_pads_background() -> None:
    args = build_args(replace(SPEC, fit="contain", scale_flags="neighbor", pad_color="pink"))
    assert "force_original_aspect_ratio=decrease:flags=neighbor,pad=1920:1080:" in _filter(args)
    assert "color=pink" in _filter(args)


def test_preview_is_fast_and_seekable() -> None:
    args = build_args(replace(SPEC, mode="preview"))
    assert _contains(args, ["-preset", "ultrafast", "-crf", "28", "-g", "15"])


def test_overlay_uses_transparent_canvas() -> None:
    args = build_args(replace(SPEC, mode="overlay"))
    assert "/a/bg.png" not in args
    assert _contains(args, ["-f", "lavfi", "-i", "color=c=black@0:s=1920x1080:r=30,format=rgba"])
    assert ":alpha=1," in _filter(args)
    assert _contains(args, ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"])


def test_background_is_required_except_overlay() -> None:
    with pytest.raises(ValueError, match="background"):
        build_args(replace(SPEC, background=None))


def test_focus_moves_crop_and_pad() -> None:
    cover = _filter(build_args(replace(SPEC, focus=(1.0, 0.0))))
    assert "crop=1920:1080:(iw-ow)*1:(ih-oh)*0," in cover
    contain = _filter(build_args(replace(SPEC, fit="contain", focus=(0.25, 0.000001))))
    assert "pad=1920:1080:(ow-iw)*0.25:(oh-ih)*0.000001:color=black" in contain


STILL = StillSpec(
    size=(1080, 1080),
    background=Path("/a/bg.png"),
    subtitles=Path("/s/thumbnail.ass"),
    fontsdir=Path("/c/fonts"),
)


def test_still_draws_ass_on_one_frame() -> None:
    args = build_still_args(STILL)
    assert _contains(args, ["-i", "/a/bg.png"])
    assert "-ss" not in args and "-loop" not in args
    assert _filter(args) == (
        "[0:v]scale=1080:1080:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1080:1080:(iw-ow)*0.5:(ih-oh)*0.5,setsar=1,format=rgb24,"
        "subtitles=filename=/s/thumbnail.ass:fontsdir=/c/fonts[v]"
    )
    assert _contains(args, ["-frames:v", "1", "-update", "1", "-c:v", "png"])
    assert _contains(args, ["-compression_level", "9"])


def test_still_seeks_only_animated_backgrounds() -> None:
    gif = build_still_args(replace(STILL, background=Path("/a/loop.gif"), at=83.5))
    assert _contains(gif, ["-ss", "83.500", "-i", "/a/loop.gif"])
    assert "-stream_loop" not in gif  # 長さを超える at はエラーにするので、繰り返さない
    assert "-ss" not in build_still_args(replace(STILL, background=Path("/a/loop.gif"), at=0))
    # 画像に -ss を付けると ffmpeg は何も書かない
    assert "-ss" not in build_still_args(replace(STILL, at=1.0))


def test_still_background_only() -> None:
    args = build_still_args(replace(STILL, subtitles=None, fontsdir=None))
    assert "subtitles" not in _filter(args)
