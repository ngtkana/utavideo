"""歌詞 .ass の読み込み・検査と、書き出し用スクリプトの合成。"""

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pysubs2

from utavideo import fonts
from utavideo.config import OverlayText, Song, format_setting
from utavideo.errors import UtavideoError

OVERLAY_LAYER = 100

# POS_TAG と OVERRIDE_BLOCK は layout も使う（.ass のタグの書き方を2か所に持たない）
POS_TAG = re.compile(r"\\(?:pos|move)\s*\(")
OVERRIDE_BLOCK = re.compile(r"(\{[^}]*\})")  # 分割にも使うのでブロックを捕捉する

_FADE_TAG = re.compile(r"\\fade?\s*\(")
_FONT_TAG = re.compile(r"\\fn([^\\}]*)")
_RESET_TAG = re.compile(r"\\r([^\\}]*)")


class SubtitleError(UtavideoError):
    """.ass が読めない、または合成できない。"""


@dataclass(frozen=True)
class Issue:
    level: Literal["error", "warning"]
    message: str


def load(path: Path) -> pysubs2.SSAFile:
    try:
        # Aegisub は BOM 付きで保存することがある
        return pysubs2.SSAFile.load(str(path), encoding="utf-8-sig", format_="ass")
    except Exception as e:  # pysubs2 のパースエラーは種類が多いのでまとめて扱う
        raise SubtitleError(f"{path} を読めません: {e}") from e


def dialogues(subs: pysubs2.SSAFile) -> list[pysubs2.SSAEvent]:
    return [e for e in subs.events if e.type == "Dialogue"]


def play_res(subs: pysubs2.SSAFile) -> tuple[int, int] | None:
    try:
        return int(subs.info["PlayResX"]), int(subs.info["PlayResY"])
    except (KeyError, ValueError):
        return None


def without_events(subs: pysubs2.SSAFile) -> pysubs2.SSAFile:
    """スタイルと Script Info だけを残した複製。"""
    stripped = copy.deepcopy(subs)
    stripped.events = []
    return stripped


def add_fades(subs: pysubs2.SSAFile, fade_ms: tuple[int, int]) -> None:
    """\\fad / \\fade の無い行の先頭に \\fad を入れる。"""
    if fade_ms == (0, 0):
        return
    tag = rf"\fad({fade_ms[0]},{fade_ms[1]})"
    for event in dialogues(subs):
        if _FADE_TAG.search(event.text):
            continue
        if event.text.startswith("{"):
            event.text = "{" + tag + event.text[1:]
        else:
            event.text = "{" + tag + "}" + event.text


def format_overlay_text(template: str, song: Song) -> str:
    return format_setting(
        template, "overlay_text.text", title=song.title, artist=song.artist, label=song.label
    )


def compose(
    lyrics: pysubs2.SSAFile,
    *,
    song: Song,
    overlay: OverlayText,
    fade_ms: tuple[int, int],
    duration_ms: int,
    include_lyrics: bool,
    font_index: fonts.FontIndex,
) -> pysubs2.SSAFile:
    """書き出しに使うスクリプトを作る。元の lyrics は変更しない。"""
    script = copy.deepcopy(lyrics) if include_lyrics else without_events(lyrics)
    add_fades(script, fade_ms)
    if overlay.enabled:
        script.events.append(
            pysubs2.SSAEvent(
                start=0,
                end=duration_ms,
                style=overlay.style,
                layer=OVERLAY_LAYER,
                text=format_overlay_text(overlay.text, song),
            )
        )
    _normalize_font_names(script, font_index)
    return script


def _display_name(font_index: fonts.FontIndex, name: str) -> str:
    """先頭の @（縦書き指定）を残したまま、索引にある表記に揃える。"""
    if name.startswith("@"):
        return "@" + font_index.display_name(name[1:])
    return font_index.display_name(name)


def _normalize_font_names(script: pysubs2.SSAFile, font_index: fonts.FontIndex) -> None:
    """フォント名を、索引にあるフォントファイルが実際に持つ表記に揃える。libass は .ass の
    名前とフォント内の名前をそのまま比べるので、Unicode の正規化が違うと（フォントが
    見つかっていても）別のフォントで描かれる。索引に無い名前はそのまま残す（この後の
    検査でエラーになる）。"""
    for style in script.styles.values():
        style.fontname = _display_name(font_index, style.fontname)
    for event in script.events:
        event.text = _FONT_TAG.sub(lambda m: "\\fn" + _display_name(font_index, m.group(1)), event.text)


def _reset_styles(text: str) -> set[str]:
    """\\r で切り替えている先のスタイル名。引数の無い \\r は元のスタイルに戻すだけなので含めない。"""
    return {name for raw in _RESET_TAG.findall(text) if (name := raw.strip())}


def used_fonts(subs: pysubs2.SSAFile) -> set[str]:
    """表示される行が使うフォント名（スタイル、\\r の切替先、\\fn タグ）。"""
    names: set[str] = set()
    for event in dialogues(subs):
        for name in {event.style, *_reset_styles(event.text)}:
            if (style := subs.styles.get(name)) is not None:
                names.add(style.fontname)
        names.update(name.strip() for name in _FONT_TAG.findall(event.text))
    # 先頭の @ は縦書き指定で、フォント名そのものではない
    return {name.removeprefix("@") for name in names if name}


def lint(
    subs: pysubs2.SSAFile,
    *,
    size: tuple[int, int],
    duration_ms: int,
    overlay: OverlayText,
) -> list[Issue]:
    issues: list[Issue] = []

    res = play_res(subs)
    if res is None:
        issues.append(Issue("error", "PlayResX / PlayResY がありません（Aegisub の解像度設定を確認）"))
    elif res != size:
        issues.append(
            Issue(
                "error",
                f"PlayRes {res[0]}x{res[1]} が動画サイズ {size[0]}x{size[1]} と一致しません",
            )
        )

    if overlay.enabled and overlay.style not in subs.styles:
        issues.append(Issue("error", f"overlay_text.style のスタイル {overlay.style!r} が .ass にありません"))

    events = dialogues(subs)
    used = {s for e in events for s in (e.style, *_reset_styles(e.text))}
    for style in sorted(used - set(subs.styles)):
        issues.append(Issue("error", f"未定義のスタイル {style!r} を使っている行があります"))

    positioned = [e for e in events if POS_TAG.search(e.text)]
    if positioned:
        where = ", ".join(describe(e) for e in positioned[:5])
        more = " ほか" if len(positioned) > 5 else ""
        issues.append(
            Issue(
                "warning",
                f"{len(positioned)} 行で \\pos / \\move を使っています"
                f"（位置は基本スタイルで決める）: {where}{more}",
            )
        )

    for event in events:
        if event.end <= event.start:
            issues.append(Issue("warning", f"表示時間が 0 以下の行があります: {describe(event)}"))
        elif event.start >= duration_ms:
            issues.append(Issue("warning", f"音声が終わった後に始まる行があります: {describe(event)}"))
        elif event.end > duration_ms:
            # 書き出しは音源の長さで切られるので、最後まで表示されない
            issues.append(Issue("warning", f"音声の終わりで途中で切られます: {describe(event)}"))

    issues.extend(_overlaps(events))
    return issues


def _overlaps(events: list[pysubs2.SSAEvent]) -> list[Issue]:
    """同じスタイル・レイヤーで時間が重なる行（\\pos の行は意図的とみなして除く）。"""
    groups: dict[tuple[str, int], list[pysubs2.SSAEvent]] = {}
    for event in events:
        if not POS_TAG.search(event.text):
            groups.setdefault((event.style, event.layer), []).append(event)

    issues: list[Issue] = []
    for (style, _), group in sorted(groups.items()):
        group.sort(key=lambda e: e.start)
        latest = group[0]
        for event in group[1:]:
            if event.start < latest.end:
                issues.append(
                    Issue(
                        "warning",
                        f"スタイル {style!r} の行が重なっています: {describe(latest)} と {describe(event)}",
                    )
                )
            if event.end > latest.end:
                latest = event
    return issues


def describe(event: pysubs2.SSAEvent) -> str:
    text = OVERRIDE_BLOCK.sub("", event.text).replace("\\N", " ").replace("\\n", " ")
    if len(text) > 20:
        text = text[:20] + "…"
    return f"{pysubs2.time.ms_to_str(event.start, fractions=True)}「{text}」"
