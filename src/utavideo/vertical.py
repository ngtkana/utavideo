"""本編の .ass から、縦型のショート用の .ass の雛形を作る（utavideo vertical-ass）。

座標は x・y をそれぞれの解像度の比で、
大きさ（フォント・余白・縁取り・影・文字間隔・ぼかし）は幅の比で変換する。
幅の比で文字も余白も一様に縮めるので、本編の画面に収まっていた行は縦の画面にも収まる。
"""

import copy
import math
import posixpath
import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import pysubs2

from utavideo import graph, subs
from utavideo.config import Focus, Layout, OverlayText, Vertical

SHORT_STYLE = "Short"
# このスタイル名で始まる行は、縦だけの文字（帯の曲名など）。歌詞として扱わない
VERTICAL_STYLE_PREFIX = "Vertical"
BAND_STYLE = f"{VERTICAL_STYLE_PREFIX}Band"
BASE_STYLE = "Lyrics"

# 本編の下敷きに合わせた Aegisub の表示の設定（縦横比の上書き・拡大率）を、縦の下敷きに持ち込まない
_DROPPED_PROJECT_KEYS = frozenset({"Video AR Mode", "Video AR Value", "Video Zoom Percent"})
# Aegisub が .ass から見た相対パスで書くファイル。縦用 .ass のフォルダから見たパスに付け替える
_PATH_PROJECT_KEYS = ("Audio File", "Keyframes File", "Timecodes File")
# パスではない値（?video・?dummy・dummy-audio:）と、絶対パス（/…、\…、C:…）は付け替えない
_NOT_RELATIVE_PATH = re.compile(r"[?/\\]|[A-Za-z][A-Za-z0-9+.-]*:")

# 引数が座標の組のタグ。\clip・\iclip は4つの数のとき（矩形）だけ
_COORD_TAG = re.compile(r"\\(pos|org|move|i?clip)\s*\(([^)]*)\)")
# 大きさのタグ。\fs が \fsp を先取りしないよう、長いものを前に置く。
# 符号付きの \fs+N・\fs-N は今の大きさからの相対指定なので、比で変えない
_SIZE_TAG = re.compile(r"\\(fsp|fs(?![+-])|[xy]?bord|[xy]?shad|blur)\s*(-?(?:\d+\.?\d*|\.\d+))")
# \be はぼかしを掛ける回数（整数）で、ぼかしの幅は回数の平方根に比例する
_BE_TAG = re.compile(r"\\be\s*(-?(?:\d+\.?\d*|\.\d+))")
# 座標として変換する引数の数（ほかの数は libass も読まないので、そのまま残す）
_COORD_ARG_COUNTS = {"pos": (2,), "org": (2,), "move": (4, 6), "clip": (4,), "iclip": (4,)}
_NUMBER = re.compile(r"\s*-?(?:\d+\.?\d*|\.\d+)\s*")


@dataclass(frozen=True)
class Conversion:
    script: pysubs2.SSAFile
    # 座標を変換できなかった行（図形・ベクターの \clip）の説明
    unconverted: list[str]


def convert(
    source: pysubs2.SSAFile,
    *,
    size: tuple[int, int],
    video_file: str,
    source_dir: str = ".",
    include_lyrics: bool = True,
    band_video_size: tuple[int, int] | None = None,
    band_frame_y: float = 0.5,
) -> Conversion:
    """本編の .ass を縦の解像度 size に変換した複製を作る。source は変更しない。

    video_file は、Aegisub で開く縦の下敷きの、縦用 .ass から見たパス。
    source_dir は、本編の .ass のフォルダの、縦用 .ass のフォルダから見たパス（/ 区切り）。
    include_lyrics が False なら、スタイルだけを写して行は写さない
    （blur では歌詞が本編の映像に入るので、縦用 .ass に写すと二重になる）。
    band_video_size を渡すと（blur を使うとき）、帯（スタイル VerticalBand）の MarginV を、
    band_frame_y（vertical.frame_y）の帯にだいたい収まる値にする。
    """
    res = subs.play_res(source)
    if res is None:
        raise subs.SubtitleError("本編の .ass に PlayResX / PlayResY が無いので、座標の比を決められません")
    rx, ry = size[0] / res[0], size[1] / res[1]
    script = copy.deepcopy(source) if include_lyrics else subs.without_events(source)

    script.info["PlayResX"] = str(size[0])
    script.info["PlayResY"] = str(size[1])
    # 本編の値が残ると libass が文字を潰して描く。PlayRes と同じ比で変えて、縦横比を縦に合わせる。
    # \blur と、ScaledBorderAndShadow: no のときの縁取り・影は LayoutRes に反比例するので、
    # PlayRes と同じ比にすれば本編との比率が保たれる。無いときは足さない（ffmpeg では無くても同じ描画になる）
    if (layout := subs.layout_res(source)) is not None:
        script.info["LayoutResX"] = str(round(layout[0] * rx))
        script.info["LayoutResY"] = str(round(layout[1] * ry))
    elif "LayoutResX" in script.info or "LayoutResY" in script.info:  # 片方だけは libass が使わない
        script.info["LayoutResX"] = str(size[0])
        script.info["LayoutResY"] = str(size[1])
    _retarget_project(script, video_file, source_dir)

    for style in script.styles.values():
        _scale_style(style, rx)
    base = script.styles.get(BASE_STYLE) or next(iter(script.styles.values()), pysubs2.SSAStyle())
    # Aegisub のスタイル一覧から選べるように足す。フォントは歌詞と同じにして、フォントが無いエラーを避ける
    if SHORT_STYLE not in script.styles:
        script.styles[SHORT_STYLE] = base.copy()
    if BAND_STYLE not in script.styles:
        band = base.copy()
        band.alignment = pysubs2.Alignment.TOP_CENTER
        if band_video_size is not None:
            band.marginv = _band_margin_v(size, band_video_size, band_frame_y, band.fontsize)
        script.styles[BAND_STYLE] = band

    unconverted: list[str] = []
    for event in script.events:
        # コメント行も、後で Dialogue に戻したときに合うよう変換する
        event.marginl, event.marginr, event.marginv = (
            round(m * rx) for m in (event.marginl, event.marginr, event.marginv)
        )
        text, skipped = convert_tags(event.text, rx, ry)
        event.text = text
        if skipped:
            unconverted.append(f"{subs.describe(event)}（{'・'.join(skipped)}）")
    return Conversion(script, unconverted)


def _band_margin_v(
    vertical_size: tuple[int, int], video_size: tuple[int, int], frame_y: float, fontsize: float
) -> int:
    """帯（スタイル VerticalBand、上揃え）の文字がだいたい帯の中央に来る MarginV。"""
    frame_h = graph.frame_height(video_size, vertical_size[0])
    band_height = (vertical_size[1] - frame_h) * frame_y
    return round(max(0, (band_height - fontsize) / 2))


def _retarget_project(script: pysubs2.SSAFile, video_file: str, source_dir: str) -> None:
    project = script.aegisub_project
    old_video = project.get("Video File")
    audio_from_video = old_video is not None and project.get("Audio File") == old_video
    for key in _DROPPED_PROJECT_KEYS:
        project.pop(key, None)
    for key in _PATH_PROJECT_KEYS:
        if (path := project.get(key)) is not None:
            project[key] = _rebase(path, source_dir)
    # 音声を下敷きの動画から読んでいたなら、音声も縦の下敷きから読む
    if audio_from_video:
        project["Audio File"] = video_file
    project["Video File"] = video_file


def _rebase(path: str, source_dir: str) -> str:
    """本編の .ass から見た相対パスを、縦用 .ass から見たパスにする。"""
    if not path or source_dir == "." or _NOT_RELATIVE_PATH.match(path):
        return path
    return posixpath.normpath(posixpath.join(source_dir, path.replace("\\", "/")))


def _scale_style(style: pysubs2.SSAStyle, ratio: float) -> None:
    for name in ("fontsize", "outline", "shadow", "spacing"):
        setattr(style, name, round(getattr(style, name) * ratio, 2))
    for name in ("marginl", "marginr", "marginv"):  # 余白は整数
        setattr(style, name, round(getattr(style, name) * ratio))


def convert_tags(text: str, rx: float, ry: float) -> tuple[str, list[str]]:
    """行の上書きタグの座標と大きさを変換する。変換しなかったものの名前も返す。"""
    skipped: dict[str, None] = {}  # 出てきた順に、重ねずに並べる

    def block(match: re.Match[str]) -> str:
        tags = match.group(0)
        if subs.starts_drawing(tags):
            skipped["図形（\\p）"] = None
        tags = _COORD_TAG.sub(lambda m: _convert_coords(m, rx, ry, skipped), tags)
        tags = _SIZE_TAG.sub(lambda m: f"\\{m[1]}{_format(float(m[2]) * rx)}", tags)
        return _BE_TAG.sub(lambda m: f"\\be{_scale_be(float(m[1]), rx)}", tags)

    return subs.OVERRIDE_BLOCK.sub(block, text), list(skipped)


def _scale_be(count: float, ratio: float) -> int:
    """\\be の回数を、ぼかしの幅が ratio 倍になるように変える。

    libass は回数を四捨五入し（2.5 は 3 回）、幅はおおむね回数の平方根に比例するので、
    回数は ratio の2乗倍にする。
    ぼかしが消えないよう、1回以上掛けていたものは1回以上に保つ（docs/verification/20260917-vertical-ass.md）。
    """
    times = math.floor(count + 0.5)
    return max(1, math.floor(times * ratio * ratio + 0.5)) if times > 0 else 0


def _convert_coords(match: re.Match[str], rx: float, ry: float, skipped: dict[str, None]) -> str:
    name, raw = match[1], match[2]
    args = raw.split(",")
    if not all(_NUMBER.fullmatch(arg) for arg in args):
        # \clip(m 0 0 l ...)・\clip(1,m ...) はベクターの図形
        skipped[f"ベクターの \\{name}"] = None
        return match.group(0)
    if len(args) not in _COORD_ARG_COUNTS[name]:
        return match.group(0)
    # x・y が交互に並ぶ。\move の5つ目と6つ目は時刻なので変えない
    values = [_format(float(arg) * (rx, ry)[i % 2]) if i < 4 else arg.strip() for i, arg in enumerate(args)]
    return f"\\{name}({','.join(values)})"


def _format(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def preview_bg_output(build_dir: Path) -> Path:
    return build_dir / "preview" / "vertical-bg.mp4"


def lyrics_path(root: Path, config: Vertical) -> Path:
    lyrics = config.lyrics
    return lyrics if lyrics.is_absolute() else root / lyrics


def focus(config: Vertical, video_focus: Focus) -> Focus:
    return config.focus or video_focus


def overlay_text(overlay: OverlayText, config: Vertical) -> OverlayText:
    """縦で使う曲名表示の設定。vertical.overlay_text = false なら出さない。"""
    return overlay.model_copy(update={"enabled": overlay.enabled and config.overlay_text})


def draws_lyrics(layouts: Collection[Layout]) -> bool:
    """縦用 .ass に歌詞を持たせるか。

    blur では歌詞が本編の映像に入るので持たせない。reframe が1つでもあれば持たせる。
    """
    return "reframe" in layouts


def script_overlay_text(overlay: OverlayText, layouts: Collection[Layout]) -> OverlayText:
    """縦用 .ass に描く曲名表示。

    reframe では本編と同じスタイル（既定 Title）で描く。blur では本編の映像には焼き込まず、
    帯（スタイル VerticalBand）に描く。
    """
    if draws_lyrics(layouts):
        return overlay
    return overlay.model_copy(update={"style": BAND_STYLE})
