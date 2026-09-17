"""本編の .ass から、縦型のショート用の .ass の雛形を作る（utavideo vertical-ass）。

座標は x・y をそれぞれの解像度の比で、大きさ（フォント・余白・縁取り・影・文字間隔）は幅の比で変換する。
幅の比で文字も余白も一様に縮めるので、本編の画面に収まっていた行は縦の画面にも収まる。
"""

import copy
import re
from dataclasses import dataclass

import pysubs2

from utavideo import subs

SHORT_STYLE = "Short"
BAND_STYLE = "VerticalBand"
BASE_STYLE = "Lyrics"

# 本編の下敷きに合わせた Aegisub の表示の設定（縦横比の上書き・拡大率）を、縦の下敷きに持ち込まない
_DROPPED_PROJECT_KEYS = frozenset({"Video AR Mode", "Video AR Value", "Video Zoom Percent"})

# 引数が座標の組のタグ。\clip・\iclip は4つの数のとき（矩形）だけ
_COORD_TAG = re.compile(r"\\(pos|org|move|i?clip)\s*\(([^)]*)\)")
# 大きさのタグ。\fs が \fsp を先取りしないよう、長いものを前に置く。
# 符号付きの \fs+N・\fs-N は今の大きさからの相対指定なので、比で変えない
_SIZE_TAG = re.compile(r"\\(fsp|fs(?![+-])|[xy]?bord|[xy]?shad)\s*(-?(?:\d+\.?\d*|\.\d+))")
# 座標として変換する引数の数（ほかの数は libass も読まないので、そのまま残す）
_COORD_ARG_COUNTS = {"pos": (2,), "org": (2,), "move": (4, 6), "clip": (4,), "iclip": (4,)}
_DRAWING_TAG = re.compile(r"\\p\s*0*[1-9]")
_NUMBER = re.compile(r"\s*-?(?:\d+\.?\d*|\.\d+)\s*")


@dataclass(frozen=True)
class Conversion:
    script: pysubs2.SSAFile
    # 座標を変換できなかった行（図形・ベクターの \clip）の説明
    unconverted: list[str]


def convert(source: pysubs2.SSAFile, *, size: tuple[int, int], video_file: str) -> Conversion:
    """本編の .ass を縦の解像度 size に変換した複製を作る。source は変更しない。

    video_file は、Aegisub で開く縦の下敷きの、.ass から見たパス。
    """
    res = subs.play_res(source)
    if res is None:
        raise subs.SubtitleError("本編の .ass に PlayResX / PlayResY が無いので、座標の比を決められません")
    rx, ry = size[0] / res[0], size[1] / res[1]
    script = copy.deepcopy(source)

    script.info["PlayResX"] = str(size[0])
    script.info["PlayResY"] = str(size[1])
    # 残っていると libass が文字を潰して描く。無いときは足さない（ffmpeg では無くても同じ描画になる）
    if "LayoutResX" in script.info or "LayoutResY" in script.info:
        script.info["LayoutResX"] = str(size[0])
        script.info["LayoutResY"] = str(size[1])
    _retarget_project(script, video_file)

    for style in script.styles.values():
        _scale_style(style, rx)
    base = script.styles.get(BASE_STYLE) or next(iter(script.styles.values()), pysubs2.SSAStyle())
    # Aegisub のスタイル一覧から選べるように足す。フォントは歌詞と同じにして、フォントが無いエラーを避ける
    if SHORT_STYLE not in script.styles:
        script.styles[SHORT_STYLE] = base.copy()
    if BAND_STYLE not in script.styles:
        band = base.copy()
        band.alignment = pysubs2.Alignment.TOP_CENTER
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


def _retarget_project(script: pysubs2.SSAFile, video_file: str) -> None:
    project = script.aegisub_project
    old_video = project.get("Video File")
    for key in _DROPPED_PROJECT_KEYS:
        project.pop(key, None)
    # 音声を下敷きの動画から読んでいたなら、音声も縦の下敷きから読む
    if old_video is not None and project.get("Audio File") == old_video:
        project["Audio File"] = video_file
    project["Video File"] = video_file


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
        if _DRAWING_TAG.search(tags):
            skipped["図形（\\p）"] = None
        tags = _COORD_TAG.sub(lambda m: _convert_coords(m, rx, ry, skipped), tags)
        return _SIZE_TAG.sub(lambda m: f"\\{m[1]}{_format(float(m[2]) * rx)}", tags)

    return subs.OVERRIDE_BLOCK.sub(block, text), list(skipped)


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
