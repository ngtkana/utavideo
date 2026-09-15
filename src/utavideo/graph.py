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

_COMMON = ["-hide_banner", "-nostdin", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y"]
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


def background_input(path: Path, fps: int) -> list[str]:
    if path.suffix.lower() in ANIMATED_EXTS:
        return ["-stream_loop", "-1", "-i", str(path)]
    return ["-loop", "1", "-framerate", str(fps), "-i", str(path)]


def fit_filter(size: tuple[int, int], fit: str, flags: str, pad_color: str) -> str:
    w, h = size
    if fit == "cover":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase:flags={flags},crop={w}:{h}"
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags={flags},"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={pad_color}"
    )


def subtitles_filter(spec: RenderSpec, *, alpha: bool = False) -> str:
    f = (
        f"subtitles=filename={escape_filter_arg(str(spec.subtitles))}"
        f":fontsdir={escape_filter_arg(str(spec.fontsdir))}"
    )
    return f + ":alpha=1" if alpha else f


def build_args(spec: RenderSpec) -> list[str]:
    """出力ファイル名を除いた ffmpeg の引数。入力 0 が映像、入力 1 が音声。"""
    w, h = spec.size
    if spec.mode == "overlay":
        inputs = ["-f", "lavfi", "-i", f"color=c=black@0:s={w}x{h}:r={spec.fps},format=rgba"]
        video = f"[0:v]{subtitles_filter(spec, alpha=True)},{_TO_BT709},format=yuva444p10le[v]"
        codec = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"]
        codec += ["-c:a", "pcm_s24le"]
    else:
        if spec.background is None:
            raise ValueError(f"mode={spec.mode} には background が必要です")
        inputs = background_input(spec.background, spec.fps)
        # YUV 上で合成すると .ass の色が変換行列の違いでずれるため、RGB で合成してから YUV にする
        video = (
            f"[0:v]{fit_filter(spec.size, spec.fit, spec.scale_flags, spec.pad_color)},"
            f"setsar=1,fps={spec.fps},format=rgb24,{subtitles_filter(spec)},"
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
