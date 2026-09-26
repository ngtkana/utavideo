"""ffmpeg の引数（入力・filtergraph・エンコード設定）を組み立てる。実行は ffmpeg.py が行う。"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from utavideo.ffmpeg import LoudnormMeasurement, LoudnormTarget
from utavideo.score import NoteEvent

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
ANIMATED_EXTS = frozenset({".gif", ".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"})
AUDIO_EXTS = frozenset({".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus"})

# Aegisub でシークしやすいよう、プレビューはキーフレームを細かく入れる
PREVIEW_GOP = 15

type Mode = Literal["final", "preview", "overlay"]
type PitchMethod = Literal["rubberband", "atempo"]
type Fit = Literal["cover", "contain"]
type ScaleFlags = Literal["lanczos", "bicubic", "bilinear", "area", "neighbor"]
# [[layers]] のアンカー。.ass の \an（テンキー配置）と同じ9方向
type LayerAnchor = Literal[
    "top-left", "top", "top-right",
    "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
]  # fmt: skip
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
class Clip:
    """曲の一部だけを書き出す区間。フレームの番号（fps で数える）で、end_frame は含まない。"""

    start_frame: int
    end_frame: int
    audio_fade_ms: tuple[int, int]  # 区間の端の音声のフェード（イン, アウト）

    def duration_s(self, fps: int) -> float:
        return (self.end_frame - self.start_frame) / fps


@dataclass(frozen=True)
class LayerSpec:
    """[[layers]] 1個ぶんの overlay 情報。区間は秒（None は無期限）。

    start・end は曲の絶対時刻。RenderSpec.background は -ss でシークしないので、
    overlay の enable にそのまま渡せば .ass と同じ時刻系になる（layers.spec の docstring 参照）。
    """

    file: Path
    scale: float
    anchor: LayerAnchor
    margin: tuple[int, int]
    layer: int
    start: float | None = None  # None なら動画の最初から
    end: float | None = None  # None なら動画の最後まで


@dataclass(frozen=True)
class Frame:
    """blur の画面で、ぼかした帯の上に置く本編の映像。

    本編を size に作ってから幅いっぱいに縮め、上下中央に置く。
    """

    size: tuple[int, int]  # 本編の解像度（[video].size）
    focus: tuple[float, float]  # 本編の focus（[video].focus）
    subtitles: Path  # 本編の合成した .ass（歌詞・曲名表示入り）
    fit: Fit = "cover"
    layers: tuple[LayerSpec, ...] = ()  # 本編と同じ画面に重ねる [[layers]]


@dataclass(frozen=True)
class Pitch:
    """inst のキー変更。ratio は周波数の比（1.0 が変化なし）。method は既定値を置かない

    （渡し忘れると rubberband と atempo のどちらで変えたか黙って決まってしまうため、focus と同じ理由）。
    """

    ratio: float
    method: PitchMethod


@dataclass(frozen=True)
class Loudnorm:
    target: LoudnormTarget
    measured: LoudnormMeasurement


@dataclass(frozen=True)
class ScoreOverlay:
    """instの画面に重ねる楽譜の横スクロール表示（issue #143）。

    events の時刻は、1小節目の頭からのオフセット（[inst.score].first_bar_offset_s）を
    呼び出し側で足し込んだ、音源上の秒に揃えてから渡すこと。
    """

    image: Path  # score.svg_to_png が書き出した横1段のPNG
    events: tuple[NoteEvent, ...]
    play_x: int  # 画面上の再生位置(px)
    y: int  # 画面上の縦位置(px)。楽譜の帯の上端


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
    # None なら背景を size に合わせる画面（本編・wide 版など）。
    # あれば blur の画面で、真ん中に frame の映像を重ねる（size は縦の解像度）
    frame: Frame | None = None
    pitch: Pitch | None = None  # None なら音声はそのまま（inst のキー変更）
    loudnorm: Loudnorm | None = None  # None なら音量はそのまま（inst の正規化）
    # frame があるときは無視される（frame.layers を使う。同時に両方を重ねることはしない）
    layers: tuple[LayerSpec, ...] = ()
    score: ScoreOverlay | None = None  # None なら楽譜を重ねない（inst の楽譜表示）


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


def _vp9_alpha_args(path: Path) -> list[str]:
    """VP9 アルファ付き .webm は、既定のデコーダーだとアルファが失われるため明示する（issue #111）。"""
    return ["-c:v", "libvpx-vp9"] if path.suffix.lower() == ".webm" else []


def layer_input(path: Path, fps: int) -> list[str]:
    """[[layers]] の素材の入力。background_input と同じ判定（画像は静止、それ以外はループ）を使う。"""
    return [*_vp9_alpha_args(path), *background_input(path, fps)]


def layer_still_input(path: Path, at: float | None) -> list[str]:
    """[[layers]] の素材から1フレームだけ読む入力（サムネイル用）。"""
    return [*_vp9_alpha_args(path), *frame_input(path, at)]


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


# [[layers]] のアンカーを、.ass の \an（テンキー配置）と同じ9方向の比率に見立てたもの
_ANCHOR_RATIOS: dict[LayerAnchor, tuple[float, float]] = {
    "top-left": (0, 0), "top": (0.5, 0), "top-right": (1, 0),
    "left": (0, 0.5), "center": (0.5, 0.5), "right": (1, 0.5),
    "bottom-left": (0, 1), "bottom": (0.5, 1), "bottom-right": (1, 1),
}  # fmt: skip


def _overlay_axis(ratio: float, main: str, over: str, margin: int) -> str:
    """overlay の x・y の式（片方の軸）。margin は辺から内側への距離（負なら画面外に出せる）。

    中央寄せ（ratio = 0.5）では、margin はどちらの辺の内側かを決められないので無視する
    （.ass の Alignment 中央でも MarginL/R が中央位置をずらさないのと同じ考え方）。
    """
    if ratio == 0:
        return str(margin)
    if ratio == 1:
        return f"({main}-{over})-({margin})"
    return f"({main}-{over})/2"


def _overlay_position(anchor: LayerAnchor, margin: tuple[int, int]) -> tuple[str, str]:
    rx, ry = _ANCHOR_RATIOS[anchor]
    return _overlay_axis(rx, "W", "w", margin[0]), _overlay_axis(ry, "H", "h", margin[1])


def _enable_clause(layer: LayerSpec) -> str:
    """overlay の enable オプション（区間の無いレイヤーは常に表示するので空文字列）。"""
    start, end = layer.start, layer.end
    if start is None and end is None:
        return ""
    if end is None:
        assert start is not None
        expr = f"gte(t,{_seconds(start)})"
    elif start is None:
        expr = f"lte(t,{_seconds(end)})"
    else:
        expr = f"between(t,{_seconds(start)},{_seconds(end)})"
    return f":enable='{expr}'"


def _layer_scale_filter(layer: LayerSpec) -> str:
    return f"scale=iw*{_ratio(layer.scale)}:ih*{_ratio(layer.scale)}"


def _video_layer_filter(layer: LayerSpec, fps: int) -> str:
    # fps を素材にも通し、本編と同じコマ番号に揃える（issue #111。ループのつなぎ目のずれを防ぐ）
    return f"fps={fps},{_layer_scale_filter(layer)}"


def _stack_layers(
    label: str, layers: list[tuple[int, LayerSpec]], source_filter: Callable[[LayerSpec], str]
) -> tuple[list[str], str]:
    """layers（layer 昇順の (入力の番号, LayerSpec) の組）を label の画面に overlay で重ねる。

    (filtergraph の断片, 出力ラベル) を返す。入力の番号は呼び出し側が決める（-i に並べた実際の順番と
    一致させる必要があるため、layer 昇順に並べ替えた後もここでは振り直さない）。
    """
    parts: list[str] = []
    for index, layer in layers:
        src_label = f"layer{index}"
        parts.append(f"[{index}:v]{source_filter(layer)}[{src_label}]")
        x, y = _overlay_position(layer.anchor, layer.margin)
        out_label = f"ov{index}"
        parts.append(
            f"[{label}][{src_label}]overlay=x={x}:y={y}:format=rgb{_enable_clause(layer)}[{out_label}]"
        )
        label = out_label
    return parts, label


def _split_by_layer(
    layers: tuple[LayerSpec, ...],
) -> tuple[list[tuple[int, LayerSpec]], list[tuple[int, LayerSpec]]]:
    """layers を (入力の番号, LayerSpec) の組にしてから、layer < 0 / >= 0 に分けて昇順に並べる。

    入力の番号は、背景（入力 0）の次から、layers の並び順のまま数える
    （-i に並べる実際の順番と一致させるため。groupby 前に振り直すと入力とフィルタがずれる）。
    """
    indexed = list(enumerate(layers, start=1))
    back = sorted((item for item in indexed if item[1].layer < 0), key=lambda item: item[1].layer)
    front = sorted((item for item in indexed if item[1].layer >= 0), key=lambda item: item[1].layer)
    return back, front


# ffmpegの式パーサは if(lt(t,...),...) のネストが約96段までしか通らない（実測。検証: issue #142）。
# 音符レベルの区切り（1曲あたり数百〜千）には全く足りないため、overlayをenable=between(t,...)で
# 区切って連結する方式にする。1チャンクあたりの区間数は、上限の96より安全側に少なく取る
SCORE_SCROLL_CHUNK_SIZE = 80


def _score_scroll_segment_expr(play_x: int, cur: NoteEvent, nxt: NoteEvent | None) -> str:
    """区間 [cur.time_s, nxt.time_s) での overlay の x の式（1次式）。nxt が無ければ速度0で静止する。"""
    slope = (nxt.x - cur.x) / (nxt.time_s - cur.time_s) if nxt is not None else 0.0
    return f"({play_x}-({_ratio(cur.x)}+{_ratio(slope)}*(t-{_seconds(cur.time_s)})))"


def _score_scroll_expr(chunk: Sequence[NoteEvent], play_x: int) -> str:
    """chunk（隣り合う区間を結ぶ点列）を、区分線形の1本の式にする。"""
    expr = _score_scroll_segment_expr(play_x, chunk[-1], None)
    for i in range(len(chunk) - 2, -1, -1):
        seg = _score_scroll_segment_expr(play_x, chunk[i], chunk[i + 1])
        expr = f"if(lt(t,{_seconds(chunk[i + 1].time_s)}),{seg},{expr})"
    return expr


def score_scroll_filter(
    events: Sequence[NoteEvent],
    *,
    input_label: str,
    image_label: str,
    play_x: int,
    y: int = 0,
    chunk_size: int = SCORE_SCROLL_CHUNK_SIZE,
) -> tuple[str, str]:
    """楽譜画像（image_label）を、events（音符ごとのx・発音時刻）に従って画面上の play_x へ向けて
    可変速でスクロールさせる filtergraph の断片を組み立てる。(断片, 出力ラベル) を返す。

    events の時刻の範囲外は、最初の音符より前は最初の区間の速度のまま延長し、最後の音符より後は
    そこで速度0になり位置が留まる（曲が終わったらそこで止まる）。1小節目の音源上のオフセット
    （events の時刻をどれだけずらすか）はここでは扱わない（呼び出し側で events.time_s に足し込む）。

    image_label には、`format` 等のフィルタを一度だけ通した出力ではなく、入力ストリームへの
    生の参照（`1:v` など）を渡すこと。チャンクが複数（チェーンする overlay が複数）になる場合、
    フィルタ出力を素で複数の overlay にファンアウトすると、2つ目以降の overlay に画像が渡らず
    背景が透けて見える不具合を確認した（ffmpeg 9.0.2 で実測。原因は不明だが、`split` フィルタで
    明示的に複製すれば起きない。検証: issue #142）。画像に前処理が要るなら `split` で複製してから
    渡すこと。
    """
    if len(events) < 2:
        raise ValueError("events は2点以上必要です")
    chunks = [events[i : i + chunk_size + 1] for i in range(0, len(events) - 1, chunk_size)]
    parts: list[str] = []
    label = input_label
    for i, chunk in enumerate(chunks):
        expr = _score_scroll_expr(chunk, play_x)
        is_first, is_last = i == 0, i == len(chunks) - 1
        lower = "-inf" if is_first else _seconds(chunk[0].time_s)
        upper = "+inf" if is_last else _seconds(chunk[-1].time_s)
        out_label = f"score{i}"
        # format=rgb を付けないと、既定のYUV420でのブレンドになり、楽譜の細い線が滲む
        # （.ass の合成と同じ理由。_stack_layers 参照）
        parts.append(
            f"[{label}][{image_label}]overlay=eval=frame:x='{expr}':y={y}:format=rgb"
            f":enable='between(t,{lower},{upper})'[{out_label}]"
        )
        label = out_label
    return ";".join(parts), label


def subtitles_filter(subtitles: Path, fontsdir: Path, *, alpha: bool = False) -> str:
    f = f"subtitles=filename={escape_filter_arg(str(subtitles))}:fontsdir={escape_filter_arg(str(fontsdir))}"
    return f + ":alpha=1" if alpha else f


def _compose_layers(
    label: str,
    first_stage: str,
    layers: tuple[LayerSpec, ...],
    subtitles: Path,
    fontsdir: Path,
    tail: str,
    fps: int,
) -> str:
    """label の画面に first_stage を適用し、layer < 0 → 字幕 → layer >= 0 の順に重ね、tail で仕上げる。

    レイヤーの入力は、背景（入力 0）の次（1）から数える。layers が空なら、以前と同じ1本の
    comma 区切りの文字列にする（filtergraph を変えないため）。
    """
    subs_expr = subtitles_filter(subtitles, fontsdir)
    if not layers:
        return f"[{label}]{first_stage},{subs_expr},{tail}"
    back, front = _split_by_layer(layers)
    parts = [f"[{label}]{first_stage}[bg0]"]
    back_parts, current = _stack_layers("bg0", back, lambda layer: _video_layer_filter(layer, fps))
    parts += back_parts
    parts.append(f"[{current}]{subs_expr}[subs0]")
    front_parts, current = _stack_layers("subs0", front, lambda layer: _video_layer_filter(layer, fps))
    parts += front_parts
    parts.append(f"[{current}]{tail}")
    return ";".join(parts)


def build_args(spec: RenderSpec) -> list[str]:
    """出力ファイル名を除いた ffmpeg の引数。入力 0 が映像、入力 1 が音声。

    背景の後、音声の前に [[layers]] の素材を入力として並べる（frame があれば frame.layers、
    無ければ spec.layers を使う。両方が同時に効くことはない）ので、音声の入力番号はその数だけ動く。
    """
    w, h = spec.size
    clip = spec.clip
    if spec.mode == "overlay":
        if clip is not None:
            raise ValueError("mode=overlay では区間を切り出せません")
        if spec.pitch is not None:
            raise ValueError("mode=overlay ではキーを変えられません")
        if spec.loudnorm is not None:
            raise ValueError("mode=overlay では音量をそろえられません")
        if spec.score is not None:
            raise ValueError("mode=overlay では楽譜を重ねられません")
        inputs = ["-f", "lavfi", "-i", f"color=c=black@0:s={w}x{h}:r={spec.fps},format=rgba"]
        subtitles = subtitles_filter(spec.subtitles, spec.fontsdir, alpha=True)
        video = f"[0:v]{subtitles},{_TO_BT709},format=yuva444p10le[v]"
        codec = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"]
        codec += ["-c:a", "pcm_s24le"]
        layers: tuple[LayerSpec, ...] = ()
    else:
        if spec.background is None:
            raise ValueError(f"mode={spec.mode} には background が必要です")
        layers = spec.frame.layers if spec.frame is not None else spec.layers
        inputs = background_input(spec.background, spec.fps)
        for layer in layers:
            inputs += layer_input(layer.file, spec.fps)
        # YUV 上で合成すると .ass の色が変換行列の違いでずれるため、RGB で合成してから YUV にする
        # 字幕は元の時刻のまま描いてから、setpts で 0 秒に戻す。.ass の時刻をずらすと、区間の頭を
        # またぐ行の \move・\fad がずれる（docs/verification/20260918-shorts.md）
        cut, back_to_zero = (_clip_video(clip, spec.fps), "setpts=PTS-STARTPTS,") if clip else ("", "")
        tail = f"{back_to_zero}{_TO_BT709},format=yuv420p[v]"
        if spec.frame is not None:
            video = _blur_video(spec, spec.frame, cut, tail)
        else:
            fit = _fit_to_rgb(
                spec.size, spec.fit, spec.focus, flags=spec.scale_flags, pad_color=spec.pad_color
            )
            first_stage = f"{cut}fps={spec.fps},{fit}"
            video = _compose_layers(
                "0:v", first_stage, spec.layers, spec.subtitles, spec.fontsdir, tail, spec.fps
            )
        if spec.mode == "final":
            codec = ["-c:v", "libx264", "-preset", spec.preset, "-crf", str(spec.crf)]
            codec += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart"]
        else:
            codec = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-g", str(PREVIEW_GOP)]
            codec += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]

    if clip is not None and spec.pitch is not None:
        raise ValueError("clip と pitch は同時に指定できません")
    if clip is not None and spec.loudnorm is not None:
        raise ValueError("clip と loudnorm は同時に指定できません")
    if clip is not None and spec.score is not None:
        # score.events の時刻は曲全体の絶対時刻だが、clip は setpts で 0 秒に戻すため噛み合わない
        raise ValueError("clip と楽譜の表示は同時に指定できません")
    video_label = "v"
    if spec.score is not None:
        score_index = 1 + len(layers)
        inputs += background_input(spec.score.image, spec.fps)
        score_frag, video_label = score_scroll_filter(
            spec.score.events,
            input_label="v",
            image_label=f"{score_index}:v",
            play_x=spec.score.play_x,
            y=spec.score.y,
        )
        video = f"{video};{score_frag}"
    audio_index = 1 + len(layers) + (1 if spec.score is not None else 0)
    audio_filter = (
        _clip_audio(clip, spec.fps, audio_index)
        if clip
        else _audio_filter(spec.pitch, spec.loudnorm, audio_index)
    )

    return [
        "ffmpeg",
        *_COMMON,
        *inputs,
        "-i", str(spec.audio),
        "-filter_complex", video + (f";{audio_filter}" if audio_filter else ""),
        "-map", f"[{video_label}]",
        "-map", "[a]" if audio_filter else f"{audio_index}:a:0",
        *codec,
        *_BT709,
        "-ar", "48000",
        "-r", str(spec.fps),
        "-t", f"{spec.duration_s:.3f}",
    ]  # fmt: skip


# 帯のぼかし。幅に比例させて、解像度が変わっても同じ見た目にする（1080 幅で sigma = 40）
BLUR_SIGMA_RATIO = 40 / 1080
# 帯にする前に縮める倍率。細かい模様を落としてから掛けるので、同じ見た目でも速い
# （docs/verification/20260918-shorts.md・20260919-blur-band.md）
BLUR_DOWNSCALE = 4


def frame_height(size: tuple[int, int], width: int) -> int:
    """blur の真ん中に置く本編の映像の高さ。幅に合わせて縮め、偶数に丸める（yuv420p のため）。"""
    w, h = size
    return max(2, round(width * h / w / 2) * 2)


def _blur_band(size: tuple[int, int], focus: tuple[float, float], pad_color: str) -> str:
    """上下の帯にする映像。はじめから 1/4 の大きさに合わせ、ぼかしてから size に戻す。

    帯は最後にぼかすので、size いっぱいに合わせてから縮めるより速い
    （docs/verification/20260919-blur-band.md）。
    縮めるときは area（画素の平均）で細かい模様を落とし、戻すときは bilinear で滑らかにする
    （lanczos は輪郭を立てるので、ぼかした絵には使わない）。
    """
    w, h = size
    small = (max(1, w // BLUR_DOWNSCALE), max(1, h // BLUR_DOWNSCALE))
    sigma = w * BLUR_SIGMA_RATIO / BLUR_DOWNSCALE
    fitted = _fit_to_rgb(small, "cover", focus, flags="area", pad_color=pad_color)
    return f"{fitted},gblur=sigma={_ratio(sigma)},scale={w}:{h}:flags=bilinear"


def _fit_to_rgb(
    size: tuple[int, int],
    fit: Fit,
    focus: tuple[float, float],
    *,
    flags: ScaleFlags,
    pad_color: str,
) -> str:
    """背景を size に合わせて、.ass を描ける RGB のフレームにするところまで。

    .ass は RGB で描く（YUV 上で合成すると色が変換行列の違いでずれる）。
    setsar=1 は scale の後に置く。scale は表示の縦横比を保つために sar を書き換えるので、
    先に置いても 1 には揃わない（docs/verification/20260919-blur-band.md）。
    """
    fitted = fit_filter(size, fit, flags, pad_color, focus)
    return f"{fitted},setsar=1,format=rgb24"


def _blur_video(spec: RenderSpec, frame: Frame, cut: str, tail: str) -> str:
    """blur の画面の filtergraph。背景を帯と本編に分け、重ねてから縦の .ass を描く。

    帯は背景だけをぼかすので、本編の歌詞・曲名表示は上下に写り込まない。
    本編の映像は幅いっぱいに縮める（高さは frame_height で偶数にする）。
    fps は split の前に置く（帯と本編で二重にコマを合わせない）。
    frame.layers は本編と同じ画面（[frame]）に、字幕の前後で重ねる（帯には重ねない）。
    """
    width = spec.size[0]
    main = _fit_to_rgb(frame.size, frame.fit, frame.focus, flags=spec.scale_flags, pad_color=spec.pad_color)
    # 高さは frame_height で決める（検査（cli）と描画で同じ値にする）
    height = frame_height(frame.size, width)
    scale_expr = f"scale={width}:{height}:flags={spec.scale_flags}[fg]"
    fg = _compose_layers("frame", main, frame.layers, frame.subtitles, spec.fontsdir, scale_expr, spec.fps)
    return (
        f"[0:v]{cut}fps={spec.fps},split[band][frame];"
        f"[band]{_blur_band(spec.size, spec.focus, spec.pad_color)}[bg];"
        f"{fg};"
        f"[bg][fg]overlay=y=(H-h)/2:format=rgb,"
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


def _clip_audio(clip: Clip, fps: int, audio_index: int) -> str:
    """区間の音声を切り出してフェードする filtergraph（[<audio_index>:a]...[a]）。

    audio_index は音声の入力番号（背景の次、[[layers]] の数だけ動く。build_args 参照）。
    """
    start, end = clip.start_frame / fps, clip.end_frame / fps
    fade_in, fade_out = (ms / 1000 for ms in clip.audio_fade_ms)
    # 入力側の -ss は mp3・m4a で頭の数ミリ秒がデコーダーの立ち上がりで本編と違うので、atrim で切る
    audio = f"[{audio_index}:a]atrim=start={_seconds(start)}:end={_seconds(end)},asetpts=PTS-STARTPTS"
    if fade_in > 0:
        audio += f",afade=t=in:st=0:d={_seconds(fade_in)}"
    if fade_out > 0:
        audio += f",afade=t=out:st={_seconds(end - start - fade_out)}:d={_seconds(fade_out)}"
    return audio + "[a]"


_SAMPLE_RATE = 48000  # 出力の -ar 48000 と合わせる


def _audio_filter(pitch: Pitch | None, loudnorm: Loudnorm | None, audio_index: int) -> str | None:
    """pitch・loudnorm を1本につないだ filtergraph（[<audio_index>:a]...[a]）。どちらも無ければ None。"""
    parts = [_pitch_filter(pitch)] if pitch is not None else []
    if loudnorm is not None:
        parts.append(_loudnorm_filter(loudnorm))
    return f"[{audio_index}:a]{','.join(parts)}[a]" if parts else None


def _pitch_filter(pitch: Pitch) -> str:
    if pitch.method == "rubberband":
        return f"rubberband=pitch={_ratio(pitch.ratio)}"
    return _atempo_pitch_filter(pitch.ratio)


def _atempo_pitch_filter(ratio: float) -> str:
    """rubberband が無い環境向け：asetrate でピッチを変え、atempo で速度だけ戻す。"""
    filt = f"aresample={_SAMPLE_RATE},asetrate={_SAMPLE_RATE}*{_ratio(ratio)},aresample={_SAMPLE_RATE}"
    chain = _atempo_chain(1 / ratio)
    return filt + "".join(f",atempo={_ratio(t)}" for t in chain)


def _atempo_chain(tempo: float) -> list[float]:
    """atempo は 0.5〜2.0 しか受け付けないため、範囲外の値を複数の atempo に分解する。"""
    if math.isclose(tempo, 1.0):
        return []
    parts: list[float] = []
    t = tempo
    while t > 2.0 or t < 0.5:
        step = 2.0 if t > 1.0 else 0.5
        parts.append(step)
        t /= step
    parts.append(t)
    return parts


def _loudnorm_filter(loudnorm: Loudnorm) -> str:
    t, m = loudnorm.target, loudnorm.measured
    return (
        f"loudnorm=I={_ratio(t.i)}:TP={_ratio(t.tp)}:LRA={_ratio(t.lra)}:"
        f"measured_I={m.input_i}:measured_TP={m.input_tp}:measured_LRA={m.input_lra}:"
        f"measured_thresh={m.input_thresh}:offset={m.target_offset}:linear=true"
    )


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
    # enable は使わない（呼び出し側で表示するかを選別済み。utavideo.layers.spec の docstring 参照）
    layers: tuple[LayerSpec, ...] = ()


def _compose_still(fit: str, layers: tuple[LayerSpec, ...], subs_expr: str | None) -> str:
    if not layers:
        video = f"[0:v]{fit}"
        if subs_expr is not None:
            video += f",{subs_expr}"
        return f"{video}[v]"
    back, front = _split_by_layer(layers)
    parts = [f"[0:v]{fit}[bg0]"]
    back_parts, label = _stack_layers("bg0", back, _layer_scale_filter)
    parts += back_parts
    if subs_expr is not None:
        parts.append(f"[{label}]{subs_expr}[subs0]")
        label = "subs0"
    front_parts, label = _stack_layers(label, front, _layer_scale_filter)
    parts += front_parts
    if label != "v":
        parts.append(f"[{label}]null[v]")
    return ";".join(parts)


def build_still_args(spec: StillSpec) -> list[str]:
    """出力ファイル名（.png）を除いた ffmpeg の引数。"""
    # 動画と同じく RGB で合成する。PNG なので YUV には戻さない
    fit = _fit_to_rgb(spec.size, spec.fit, spec.focus, flags=spec.scale_flags, pad_color=spec.pad_color)
    subs_expr: str | None = None
    if spec.subtitles is not None:
        if spec.fontsdir is None:
            raise ValueError("subtitles には fontsdir が必要です")
        subs_expr = subtitles_filter(spec.subtitles, spec.fontsdir)
    video = _compose_still(fit, spec.layers, subs_expr)
    inputs = frame_input(spec.background, spec.at)
    for layer in spec.layers:
        inputs += layer_still_input(layer.file, spec.at)
    return [
        "ffmpeg",
        *_COMMON,
        *inputs,
        "-filter_complex", video,
        "-map", "[v]",
        # 1枚だけ書く。-update 1 が無いと、連番でない名前に image2 が警告を出す
        "-frames:v", "1",
        "-update", "1",
        "-c:v", "png",
        "-pix_fmt", "rgb24",
        "-compression_level", "9",
    ]  # fmt: skip
