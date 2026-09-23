from dataclasses import replace
from pathlib import Path

import pytest

from utavideo.ffmpeg import LoudnormMeasurement, LoudnormTarget
from utavideo.graph import (
    Clip,
    Frame,
    Loudnorm,
    Pitch,
    RenderSpec,
    StillSpec,
    build_args,
    build_still_args,
    escape_filter_arg,
)

MEASURED = LoudnormMeasurement(
    input_i="-23.71", input_tp="-2.3", input_lra="4.5", input_thresh="-34.1", target_offset="0.51"
)

SPEC = RenderSpec(
    mode="final",
    size=(1920, 1080),
    fps=30,
    duration_s=12.3456,
    audio=Path("/a/mix v1.0.wav"),
    subtitles=Path("/w/final.ass"),
    fontsdir=Path("/c/fonts"),
    focus=(0.5, 0.5),
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
        "[0:v]fps=30,scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1920:1080:(iw-ow)*0.5:(ih-oh)*0.5,"
        "setsar=1,format=rgb24,subtitles=filename=/w/final.ass:fontsdir=/c/fonts,"
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
    focus=(0.5, 0.5),
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


# 区間は 345〜820 フレーム（30fps で 11.5〜27.333… 秒）
CLIP_SPEC = replace(SPEC, fps=30, duration_s=475 / 30, clip=Clip(345, 820, (300, 1000)))


def test_clip_cuts_after_decoding_and_puts_the_subtitles_back_to_zero() -> None:
    video = _filter(build_args(CLIP_SPEC))
    # 入力側の -ss は使わず、デコードの直後に本編と同じコマにしてから切る
    assert "-ss" not in build_args(CLIP_SPEC)
    assert video.startswith("[0:v]fps=30,trim=start_pts=345:end_pts=820,")
    # 字幕は元の時刻のまま描いてから 0 秒に戻す
    assert video.index("subtitles=") < video.index("setpts=PTS-STARTPTS")


def test_clip_trims_and_fades_the_audio() -> None:
    audio = _filter(build_args(CLIP_SPEC)).split(";")[1]
    assert audio == (
        "[1:a]atrim=start=11.500000:end=27.333333,asetpts=PTS-STARTPTS,"
        "afade=t=in:st=0:d=0.300000,afade=t=out:st=14.833333:d=1.000000[a]"
    )
    assert _contains(build_args(CLIP_SPEC), ["-map", "[a]"])


def test_clip_without_fades_has_no_afade() -> None:
    audio = _filter(build_args(replace(CLIP_SPEC, clip=Clip(0, 300, (0, 0))))).split(";")[1]
    assert "afade" not in audio


def test_clip_is_rejected_in_overlay_mode() -> None:
    with pytest.raises(ValueError, match="overlay"):
        build_args(replace(CLIP_SPEC, mode="overlay"))


def test_pitch_none_keeps_audio_untouched() -> None:
    # pitch を渡さないとき（既存の build/preview-bg/overlay）は、今まで通り音声を直結する
    assert "rubberband" not in _filter(build_args(SPEC))
    assert _contains(build_args(SPEC), ["-map", "1:a:0"])


def test_pitch_shifts_the_audio_with_rubberband() -> None:
    pitch = Pitch(1.122462, "rubberband")
    audio = _filter(build_args(replace(SPEC, pitch=pitch))).split(";")[1]
    assert audio == "[1:a]rubberband=pitch=1.122462[a]"
    assert _contains(build_args(replace(SPEC, pitch=pitch)), ["-map", "[a]"])


def test_pitch_is_rejected_in_overlay_mode() -> None:
    with pytest.raises(ValueError, match="overlay"):
        build_args(replace(SPEC, mode="overlay", pitch=Pitch(1.122462, "rubberband")))


def test_pitch_and_clip_are_rejected_together() -> None:
    with pytest.raises(ValueError, match="pitch"):
        build_args(replace(CLIP_SPEC, pitch=Pitch(1.122462, "rubberband")))


def test_atempo_method_builds_asetrate_and_atempo_chain() -> None:
    # key=+2 相当（ratio が [0.5, 2.0] の範囲内）は atempo が1段だけになる
    pitch = Pitch(1.122462, "atempo")
    audio = _filter(build_args(replace(SPEC, pitch=pitch))).split(";")[1]
    assert audio == "[1:a]aresample=48000,asetrate=48000*1.122462,aresample=48000,atempo=0.890899[a]"


def test_atempo_chain_splits_extreme_ratios() -> None:
    # 2オクターブ上（ratio=4.0）は tempo=0.25 になり、atempo の 0.5〜2.0 制約で2段に分かれる
    audio = _filter(build_args(replace(SPEC, pitch=Pitch(4.0, "atempo")))).split(";")[1]
    assert audio.count("atempo=") == 2
    assert audio.endswith(",atempo=0.5,atempo=0.5[a]")

    # 2オクターブ下（ratio=0.25）は tempo=4.0 になり、同じく2段
    audio = _filter(build_args(replace(SPEC, pitch=Pitch(0.25, "atempo")))).split(";")[1]
    assert audio.count("atempo=") == 2
    assert audio.endswith(",atempo=2,atempo=2[a]")


def test_atempo_chain_skips_atempo_when_ratio_is_one() -> None:
    audio = _filter(build_args(replace(SPEC, pitch=Pitch(1.0, "atempo")))).split(";")[1]
    assert "atempo" not in audio


def test_loudnorm_filter_uses_measured_values() -> None:
    loudnorm = Loudnorm(LoudnormTarget(), MEASURED)
    audio = _filter(build_args(replace(SPEC, loudnorm=loudnorm))).split(";")[1]
    assert audio == (
        "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-23.71:measured_TP=-2.3:"
        "measured_LRA=4.5:measured_thresh=-34.1:offset=0.51:linear=true[a]"
    )
    assert _contains(build_args(replace(SPEC, loudnorm=loudnorm)), ["-map", "[a]"])


def test_pitch_and_loudnorm_are_chained_in_one_filter() -> None:
    pitch = Pitch(1.122462, "rubberband")
    loudnorm = Loudnorm(LoudnormTarget(), MEASURED)
    audio = _filter(build_args(replace(SPEC, pitch=pitch, loudnorm=loudnorm))).split(";")[1]
    assert audio.startswith("[1:a]rubberband=pitch=1.122462,loudnorm=")
    assert audio.endswith("[a]")
    assert audio.count("[1:a]") == 1


def test_loudnorm_is_rejected_in_overlay_mode() -> None:
    loudnorm = Loudnorm(LoudnormTarget(), MEASURED)
    with pytest.raises(ValueError, match="overlay"):
        build_args(replace(SPEC, mode="overlay", loudnorm=loudnorm))


def test_loudnorm_and_clip_are_rejected_together() -> None:
    loudnorm = Loudnorm(LoudnormTarget(), MEASURED)
    with pytest.raises(ValueError, match="loudnorm"):
        build_args(replace(CLIP_SPEC, loudnorm=loudnorm))


BLUR_SPEC = replace(
    SPEC,
    size=(1080, 1920),
    subtitles=Path("/w/vertical.ass"),
    focus=(0.5, 1.0),
    frame=Frame(size=(1920, 1080), focus=(0.5, 0.5), subtitles=Path("/w/main.ass"), frame_y=0.25),
)


def test_blur_puts_the_main_video_on_a_blurred_band() -> None:
    parts = _filter(build_args(BLUR_SPEC)).split(";")
    # コマを合わせるのは split の前で1回だけ
    assert parts[0] == "[0:v]fps=30,split[band][frame]"
    # 帯ははじめから 1/4 の大きさに合わせてぼかし、最後に戻す（focus は帯の切り取りに効く）
    assert parts[1] == (
        "[band]scale=270:480:force_original_aspect_ratio=increase:flags=area,"
        "crop=270:480:(iw-ow)*0.5:(ih-oh)*1,setsar=1,format=rgb24,"
        "gblur=sigma=10,scale=1080:1920:flags=bilinear[bg]"
    )
    # 真ん中は本編と同じ画面に本編の .ass を描いてから、幅いっぱいに縮める
    assert parts[2] == (
        "[frame]scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=1920:1080:(iw-ow)*0.5:(ih-oh)*0.5,setsar=1,format=rgb24,"
        "subtitles=filename=/w/main.ass:fontsdir=/c/fonts,scale=1080:608:flags=lanczos[fg]"
    )
    # 重ねてから縦用 .ass を描く。RGB のまま合成してから YUV にする
    assert parts[3] == (
        "[bg][fg]overlay=y=(H-h)*0.25:format=rgb,"
        "subtitles=filename=/w/vertical.ass:fontsdir=/c/fonts,"
        "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[v]"
    )


def test_blur_cuts_the_section_once_before_the_split() -> None:
    parts = _filter(build_args(replace(BLUR_SPEC, clip=Clip(345, 820, (0, 0))))).split(";")
    # 背景を1回だけ切り出してから、帯と本編に分ける
    assert parts[0] == "[0:v]fps=30,trim=start_pts=345:end_pts=820,fps=30,split[band][frame]"
    # 0 秒に戻すのも、重ねた後の1回だけ
    assert parts[3].count("setpts=PTS-STARTPTS") == 1
    assert "setpts=PTS-STARTPTS" not in parts[1] + parts[2]
