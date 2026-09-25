"""本編の .ass から、縦型のショート用の .ass の雛形を作る（utavideo preview-bg が自動で作る）。

歌詞は本編の映像に入るので写さず、スタイル（フォント・余白・縁取り・影・文字間隔・ぼかし）だけを
幅の比で一様に縮めて写す。
"""

import posixpath
import re
from pathlib import Path

import pysubs2

from utavideo import graph, subs
from utavideo.config import Focus, OverlayText, Vertical

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


def convert(
    source: pysubs2.SSAFile,
    *,
    size: tuple[int, int],
    video_file: str,
    band_video_size: tuple[int, int],
    source_dir: str = ".",
) -> pysubs2.SSAFile:
    """本編の .ass のスタイルを縦の解像度 size に変換した複製を作る。source は変更しない。

    video_file は、Aegisub で開く縦の下敷きの、縦用 .ass から見たパス。
    source_dir は、本編の .ass のフォルダの、縦用 .ass のフォルダから見たパス（/ 区切り）。
    歌詞は本編の映像に入るので、行は写さずスタイルだけを写す（縦用 .ass に写すと二重になる）。
    band_video_size は、帯（スタイル VerticalBand）の MarginV を、
    本編を中央に置いたときの帯にだいたい収まる値にするための本編の映像の大きさ。
    """
    res = subs.play_res(source)
    if res is None:
        raise subs.SubtitleError("本編の .ass に PlayResX / PlayResY が無いので、座標の比を決められません")
    rx, ry = size[0] / res[0], size[1] / res[1]
    script = subs.without_events(source)

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
        band.marginv = _band_margin_v(size, band_video_size, band.fontsize)
        script.styles[BAND_STYLE] = band

    return script


def _band_margin_v(vertical_size: tuple[int, int], video_size: tuple[int, int], fontsize: float) -> int:
    """帯（スタイル VerticalBand、上揃え）の文字がだいたい帯の中央に来る MarginV。

    本編を中央に置くので、上の帯の高さは上下の帯を合わせた高さのちょうど半分になる。
    """
    frame_h = graph.frame_height(video_size, vertical_size[0])
    band_height = (vertical_size[1] - frame_h) / 2
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


def preview_bg_output(build_dir: Path) -> Path:
    return build_dir / "preview" / "vertical-bg.mp4"


def lyrics_path(root: Path, config: Vertical) -> Path:
    lyrics = config.lyrics
    return lyrics if lyrics.is_absolute() else root / lyrics


def focus(config: Vertical, video_focus: Focus) -> Focus:
    return config.focus or video_focus


def overlay_text(overlay: OverlayText, config: Vertical) -> OverlayText:
    """縦で使う曲名表示の設定。

    歌詞は本編の映像に入るので、曲名表示は本編の映像には焼き込まず、帯（スタイル VerticalBand）に描く。
    vertical.overlay_text = false なら出さない。
    """
    return overlay.model_copy(
        update={"enabled": overlay.enabled and config.overlay_text, "style": BAND_STYLE}
    )
