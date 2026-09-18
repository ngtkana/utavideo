"""ffmpeg の引数（入力・filtergraph・エンコード設定）を組み立てる。実行は ffmpeg.py が行う。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
ANIMATED_EXTS = frozenset({".gif", ".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"})
AUDIO_EXTS = frozenset({".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus"})

# Aegisub でシークしやすいよう、プレビューはキーフレームを細かく入れる
PREVIEW_GOP = 15

type Mode = Literal["final", "preview", "overlay"]
type Fit = Literal["cover", "contain"]
# 縦の画面の作り方。reframe は背景を縦に切り取り、blur は本編を上下のぼかした帯に置く
type Layout = Literal["reframe", "blur"]
type ScaleFlags = Literal["lanczos", "bicubic", "bilinear", "area", "neighbor"]
type Preset = Literal[
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
    "placebo",
]

_COMMON = ["-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y"]
_BT709 = [
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-color_range", "tv",
]  # fmt: skip
_TO_BT709 = "scale=out_color_matrix=bt709:out_range=tv"


@dataclass(frozen=True)
class Clip:
    """曲の一部だけを書き出す区間。フレームの番号（fps で数える）で、end_frame は含まない。"""

    start_frame: int
    end_frame: int
    audio_fade_ms: tuple[int, int]  # 区間の端の音声のフェード（イン, アウト）

    def duration_s(self, fps: int) -> float:
        return (self.end_frame - self.start_frame) / fps


@dataclass(frozen=True)
class Frame:
    """blur の画面で、ぼかした帯の上に置く本編の映像。

    本編を size に作ってから幅いっぱいに縮め、上端を (H - h) * frame_y に置く。
    """

    size: tuple[int, int]  # 本編の解像度（[video].size）
    focus: tuple[float, float]  # 本編の focus（[video].focus）
    subtitles: Path  # 本編の合成した .ass（歌詞・曲名表示入り）
    frame_y: float
    fit: Fit = "cover"


@dataclass(frozen=True)
class RenderSpec:
    mode: Mode
    size: tuple[int, int]
    fps: int
    duration_s: float
    audio: Path
    subtitles: Path
    fontsdir: Path
    # 既定値を置かない。渡し忘れると video.focus が黙って効かなくなるため
    focus: tuple[float, float]
    background: Path | None = None
    fit: Fit = "cover"
    scale_flags: ScaleFlags = "lanczos"
    pad_color: str = "black"
    crf: int = 18
    preset: Preset = "slow"
    clip: Clip | None = None  # None なら曲全体
    # None なら背景を size に合わせる画面（reframe）。あれば blur の画面で、size は縦の解像度
    frame: Frame | None = None


def escape_filter_arg(value: str) -> str:
    """filtergraph のオプション値に埋め込む文字列をエスケープする。

    オプション値としてのエスケープと、filtergraph 記述としてのエスケープの2段階が必要。
    """
    for ch in "\\':":
        value = value.replace(ch, "\\" + ch)
    for ch in "\\'[],;":
        value = value.replace(ch, "\\" + ch)
    return value


def is_image(path: Path) -> bool:
    """静止画の背景か（GIF・動画ではない）。"""
    return path.suffix.lower() in IMAGE_EXTS


def background_input(path: Path, fps: int) -> list[str]:
    if not is_image(path):
        return ["-stream_loop", "-1", "-i", str(path)]
    return ["-loop", "1", "-framerate", str(fps), "-i", str(path)]


def frame_input(path: Path, at: float | None) -> list[str]:
    """背景の1フレームを読む入力。GIF・動画は at 秒へシークする（繰り返さない）。

    入力側でシークしても最初のフレームの時刻は 0 になるので、.ass の 0 秒と重なる。
    画像に -ss を付けると ffmpeg は何も書かずに正常終了するので、画像では付けない
    （docs/verification/20260917-thumbnail.md）。
    """
    if is_image(path) or not at:
        return ["-i", str(path)]
    return ["-ss", f"{at:.3f}", "-i", str(path)]


def _ratio(value: float) -> str:
    # 指数表記（1e-05）を式に入れないよう、小数で書く
    return f"{value:.6f}".rstrip("0").rstrip(".")


def fit_filter(
    size: tuple[int, int], fit: str, flags: str, pad_color: str, focus: tuple[float, float]
) -> str:
    """背景を size に合わせる。focus は cover で切り取って残す位置、contain で余白の中に寄せる位置。

    focus = (0.5, 0.5) は、以前の中央合わせ（crop の既定値、pad の /2）と同じ画素になる。
    """
    w, h = size
    x, y = map(_ratio, focus)
    if fit == "cover":
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=increase:flags={flags},"
            f"crop={w}:{h}:(iw-ow)*{x}:(ih-oh)*{y}"
        )
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags={flags},"
        f"pad={w}:{h}:(ow-iw)*{x}:(oh-ih)*{y}:color={pad_color}"
    )


def subtitles_filter(subtitles: Path, fontsdir: Path, *, alpha: bool = False) -> str:
    f = f"subtitles=filename={escape_filter_arg(str(subtitles))}:fontsdir={escape_filter_arg(str(fontsdir))}"
    return f + ":alpha=1" if alpha else f


def build_args(spec: RenderSpec) -> list[str]:
    """出力ファイル名を除いた ffmpeg の引数。入力 0 が映像、入力 1 が音声。"""
    w, h = spec.size
    clip = spec.clip
    if spec.mode == "overlay":
        if clip is not None:
            raise ValueError("mode=overlay では区間を切り出せません")
        inputs = ["-f", "lavfi", "-i", f"color=c=black@0:s={w}x{h}:r={spec.fps},format=rgba"]
        subtitles = subtitles_filter(spec.subtitles, spec.fontsdir, alpha=True)
        video = f"[0:v]{subtitles},{_TO_BT709},format=yuva444p10le[v]"
        codec = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"]
        codec += ["-c:a", "pcm_s24le"]
    else:
        if spec.background is None:
            raise ValueError(f"mode={spec.mode} には background が必要です")
        inputs = background_input(spec.background, spec.fps)
        # YUV 上で合成すると .ass の色が変換行列の違いでずれるため、RGB で合成してから YUV にする
        # 字幕は元の時刻のまま描いてから、setpts で 0 秒に戻す。.ass の時刻をずらすと、区間の頭を
        # またぐ行の \move・\fad がずれる（docs/verification/20260918-shorts.md）
        cut, back_to_zero = (_clip_video(clip, spec.fps), "setpts=PTS-STARTPTS,") if clip else ("", "")
        tail = f"{back_to_zero}{_TO_BT709},format=yuv420p[v]"
        if spec.frame is not None:
            video = _blur_video(spec, spec.frame, cut, tail)
        else:
            fit = _fit_to_rgb(spec, spec.size, spec.fit, spec.focus)
            video = f"[0:v]{cut}{fit},{subtitles_filter(spec.subtitles, spec.fontsdir)},{tail}"
        if spec.mode == "final":
            codec = ["-c:v", "libx264", "-preset", spec.preset, "-crf", str(spec.crf)]
            codec += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart"]
        else:
            codec = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-g", str(PREVIEW_GOP)]
            codec += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]

    return [
        "ffmpeg",
        *_COMMON,
        *inputs,
        "-i", str(spec.audio),
        "-filter_complex", video + (f";{_clip_audio(clip, spec.fps)}" if clip else ""),
        "-map", "[v]",
        "-map", "[a]" if clip else "1:a:0",
        *codec,
        *_BT709,
        "-ar", "48000",
        "-r", str(spec.fps),
        "-t", f"{spec.duration_s:.3f}",
    ]  # fmt: skip


# 帯のぼかし。幅に比例させて、解像度が変わっても同じ見た目にする（1080 幅で sigma = 40）
BLUR_SIGMA_RATIO = 40 / 1080
# ぼかす前に縮める倍率。細かい模様を落としてから掛けるので、同じ見た目でも速い
# （docs/verification/20260918-shorts.md）
BLUR_DOWNSCALE = 4


def blur_filter(size: tuple[int, int]) -> str:
    """帯にする映像をぼかすフィルタ。1/4 に縮めて gblur を掛け、元の大きさに戻す。

    縮めるときは area（画素の平均）で細かい模様を落とし、戻すときは bilinear で滑らかにする
    （lanczos は輪郭を立てるので、ぼかした絵には使わない）。
    """
    w, h = size
    small = (max(1, w // BLUR_DOWNSCALE), max(1, h // BLUR_DOWNSCALE))
    sigma = w * BLUR_SIGMA_RATIO / BLUR_DOWNSCALE
    return f"scale={small[0]}:{small[1]}:flags=area,gblur=sigma={_ratio(sigma)},scale={w}:{h}:flags=bilinear"


def _fit_to_rgb(spec: RenderSpec, size: tuple[int, int], fit: Fit, focus: tuple[float, float]) -> str:
    """背景を size に合わせて、.ass を描ける RGB のフレームにするところまで。

    .ass は RGB で描く（YUV 上で合成すると色が変換行列の違いでずれる）。
    """
    fitted = fit_filter(size, fit, spec.scale_flags, spec.pad_color, focus)
    return f"{fitted},setsar=1,fps={spec.fps},format=rgb24"


def _blur_video(spec: RenderSpec, frame: Frame, cut: str, tail: str) -> str:
    """blur の画面の filtergraph。背景を帯と本編に分け、重ねてから縦の .ass を描く。

    帯は背景だけをぼかすので、本編の歌詞・曲名表示は上下に写り込まない。
    本編の映像は幅いっぱいに縮める（高さが奇数にならないよう -2 で合わせる）。
    """
    width = spec.size[0]
    band = _fit_to_rgb(spec, spec.size, "cover", spec.focus)
    main = _fit_to_rgb(spec, frame.size, frame.fit, frame.focus)
    return (
        f"[0:v]{cut}split[band][frame];"
        f"[band]{band},{blur_filter(spec.size)}[bg];"
        f"[frame]{main},{subtitles_filter(frame.subtitles, spec.fontsdir)},"
        f"scale={width}:-2:flags={spec.scale_flags}[fg];"
        f"[bg][fg]overlay=y=(H-h)*{_ratio(frame.frame_y)}:format=rgb,"
        f"{subtitles_filter(spec.subtitles, spec.fontsdir)},{tail}"
    )


def _seconds(value: float) -> str:
    return f"{value:.6f}"


def _clip_video(clip: Clip, fps: int) -> str:
    """区間の外の背景を捨てるフィルタ。入力側の -ss は使わない。

    -stream_loop の2周目以降へ -ss でシークすると、本編とコマがずれる。デコードの直後に fps で
    本編と同じコマにしてから切ると、本編のフレームと一致する（docs/verification/20260918-shorts.md）。
    fps の出力の時間の単位は 1/fps なので、trim の pts はフレームの番号と同じになる。
    後ろの fps は区間を切っても残す（本編と同じフィルタの並びのままにするため）。
    """
    return f"fps={fps},trim=start_pts={clip.start_frame}:end_pts={clip.end_frame},"


def _clip_audio(clip: Clip, fps: int) -> str:
    """区間の音声を切り出してフェードする filtergraph（[1:a]...[a]）。"""
    start, end = clip.start_frame / fps, clip.end_frame / fps
    fade_in, fade_out = (ms / 1000 for ms in clip.audio_fade_ms)
    # 入力側の -ss は mp3・m4a で頭の数ミリ秒がデコーダーの立ち上がりで本編と違うので、atrim で切る
    audio = f"[1:a]atrim=start={_seconds(start)}:end={_seconds(end)},asetpts=PTS-STARTPTS"
    if fade_in > 0:
        audio += f",afade=t=in:st=0:d={_seconds(fade_in)}"
    if fade_out > 0:
        audio += f",afade=t=out:st={_seconds(end - start - fade_out)}:d={_seconds(fade_out)}"
    return audio + "[a]"


@dataclass(frozen=True)
class StillSpec:
    """背景の1フレームに .ass の 0 秒を描いた PNG。subtitles が None なら背景だけ。"""

    size: tuple[int, int]
    background: Path
    focus: tuple[float, float]  # RenderSpec と同じく既定値を置かない
    at: float | None = None
    subtitles: Path | None = None
    fontsdir: Path | None = None
    fit: Fit = "cover"
    scale_flags: ScaleFlags = "lanczos"
    pad_color: str = "black"


def build_still_args(spec: StillSpec) -> list[str]:
    """出力ファイル名（.png）を除いた ffmpeg の引数。"""
    # 動画と同じく RGB で合成する。PNG なので YUV には戻さない
    fit = fit_filter(spec.size, spec.fit, spec.scale_flags, spec.pad_color, spec.focus)
    video = f"[0:v]{fit},setsar=1,format=rgb24"
    if spec.subtitles is not None:
        if spec.fontsdir is None:
            raise ValueError("subtitles には fontsdir が必要です")
        video += f",{subtitles_filter(spec.subtitles, spec.fontsdir)}"
    return [
        "ffmpeg",
        *_COMMON,
        *frame_input(spec.background, spec.at),
        "-filter_complex", f"{video}[v]",
        "-map", "[v]",
        # 1枚だけ書く。-update 1 が無いと、連番でない名前に image2 が警告を出す
        "-frames:v", "1",
        "-update", "1",
        "-c:v", "png",
        "-pix_fmt", "rgb24",
        "-compression_level", "9",
    ]  # fmt: skip
