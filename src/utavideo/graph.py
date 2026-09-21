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

# 進捗以外を黙らせる共通の引数。見本の素材を合成するとき（sample.py）にも使う
QUIET = ["-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-y"]
_COMMON = [*QUIET, "-progress", "pipe:1"]
_BT709 = [
    "-colorspace", "bt709",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-color_range", "tv",
]  # fmt: skip
_TO_BT709 = "scale=out_color_matrix=bt709:out_range=tv"


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
    if spec.mode == "overlay":
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
        video = (
            f"[0:v]{fit_filter(spec.size, spec.fit, spec.scale_flags, spec.pad_color, spec.focus)},"
            f"setsar=1,fps={spec.fps},format=rgb24,{subtitles_filter(spec.subtitles, spec.fontsdir)},"
            f"{_TO_BT709},format=yuv420p[v]"
        )
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
        "-filter_complex", video,
        "-map", "[v]",
        "-map", "1:a:0",
        *codec,
        *_BT709,
        "-ar", "48000",
        "-r", str(spec.fps),
        "-t", f"{spec.duration_s:.3f}",
    ]  # fmt: skip


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
