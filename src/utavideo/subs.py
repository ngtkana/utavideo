"""歌詞 .ass の読み込み・検査と、書き出し用スクリプトの合成。"""

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pysubs2

from utavideo.config import OverlayText, Song, format_setting
from utavideo.errors import UtavideoError

OVERLAY_LAYER = 100

# POS_TAG と OVERRIDE_BLOCK は layout も使う（.ass のタグの書き方を2か所に持たない）
POS_TAG = re.compile(r"\\(?:pos|move)\s*\(")
OVERRIDE_BLOCK = re.compile(r"(\{[^}]*\})")  # 分割にも使うのでブロックを捕捉する
DRAWING_TAG = re.compile(r"\\p\s*(\d+)")  # 上書きタグのブロックの中で探す

_FADE_TAG = re.compile(r"\\fade?\s*\(")
_FADE_ARGS = re.compile(r"\\fade?\s*\(([^)]*)\)")
_FONT_TAG = re.compile(r"\\fn([^\\}]*)")
_RESET_TAG = re.compile(r"\\r([^\\}]*)")


class SubtitleError(UtavideoError):
    """.ass が読めない、または合成できない。"""


type IssueLevel = Literal["error", "warning"]


@dataclass(frozen=True)
class Issue:
    level: IssueLevel
    message: str


def prefixed(issues: list[Issue], prefix: str) -> list[Issue]:
    """どの .ass・どの出力についての問題かを、メッセージの頭に付ける。"""
    return [Issue(i.level, prefix + i.message) for i in issues]


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


def layout_res(subs: pysubs2.SSAFile) -> tuple[int, int] | None:
    """LayoutResX / LayoutResY。libass は2つとも揃っているときだけ使うので、片方だけなら None。"""
    try:
        return int(subs.info["LayoutResX"]), int(subs.info["LayoutResY"])
    except (KeyError, ValueError):
        return None


def without_events(subs: pysubs2.SSAFile) -> pysubs2.SSAFile:
    """スタイルと Script Info だけを残した複製。"""
    stripped = copy.deepcopy(subs)
    stripped.events = []
    return stripped


def add_fades(
    subs: pysubs2.SSAFile, fade_ms: tuple[int, int], *, no_fade_style_prefix: str | None = None
) -> None:
    """\\fad / \\fade の無い行の先頭に \\fad を入れる。

    スタイル名が no_fade_style_prefix で始まる行には入れない。
    """
    if fade_ms == (0, 0):
        return
    tag = rf"\fad({fade_ms[0]},{fade_ms[1]})"
    for event in dialogues(subs):
        if _FADE_TAG.search(event.text):
            continue
        if no_fade_style_prefix is not None and event.style.startswith(no_fade_style_prefix):
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
    no_fade_style_prefix: str | None = None,
) -> pysubs2.SSAFile:
    """書き出しに使うスクリプトを作る。元の lyrics は変更しない。

    スタイル名が no_fade_style_prefix で始まる行には、自動のフェードを入れない。
    """
    script = copy.deepcopy(lyrics) if include_lyrics else without_events(lyrics)
    add_fades(script, fade_ms, no_fade_style_prefix=no_fade_style_prefix)
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
    return script


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


def _play_res_issues(subs: pysubs2.SSAFile, size: tuple[int, int], label: str) -> list[Issue]:
    res = play_res(subs)
    if res is None:
        return [Issue("error", "PlayResX / PlayResY がありません（Aegisub の解像度設定を確認）")]
    issues: list[Issue] = []
    if res != size:
        message = f"PlayRes {res[0]}x{res[1]} が{label} {size[0]}x{size[1]} と一致しません"
        issues.append(Issue("error", message))
    return issues + layout_res_issues(subs)


def layout_res_issues(subs: pysubs2.SSAFile) -> list[Issue]:
    """LayoutResX / LayoutResY の縦横比が PlayRes と違うときのエラー。PlayRes が無ければ見ない。"""
    res, layout = play_res(subs), layout_res(subs)
    if res is None or layout is None or layout[0] * res[1] == layout[1] * res[0]:
        return []
    # libass は LayoutRes と PlayRes の縦横比の違いの分だけ、文字を横か縦に潰して描く。
    # 縦横比が同じで大きさだけ違うときは文字の形・位置は変わらないので止めない
    # （docs/verification/20260917-vertical-ass.md）
    message = (
        f"LayoutResX / LayoutResY {layout[0]}x{layout[1]} の縦横比が"
        f" PlayRes {res[0]}x{res[1]} と違うので、"
        "文字が潰れて描かれます"
        "（テキストエディタで LayoutResX・LayoutResY の行を消すか、PlayRes と同じ値にする）"
    )
    return [Issue("error", message)]


def _undefined_style_issues(subs: pysubs2.SSAFile) -> list[Issue]:
    used = {s for e in dialogues(subs) for s in (e.style, *_reset_styles(e.text))}
    return [
        Issue("error", f"未定義のスタイル {style!r} を使っている行があります")
        for style in sorted(used - set(subs.styles))
    ]


def _overlay_style_issues(subs: pysubs2.SSAFile, overlay: OverlayText) -> list[Issue]:
    if overlay.enabled and overlay.style not in subs.styles:
        return [Issue("error", f"overlay_text.style のスタイル {overlay.style!r} が .ass にありません")]
    return []


def lint(
    subs: pysubs2.SSAFile,
    *,
    size: tuple[int, int],
    duration_ms: int,
    overlay: OverlayText,
) -> list[Issue]:
    issues = _play_res_issues(subs, size, "動画サイズ")
    issues += _overlay_style_issues(subs, overlay)
    issues += _undefined_style_issues(subs)
    return issues + lint_lines(dialogues(subs), duration_ms=duration_ms)


def lint_lines(events: list[pysubs2.SSAEvent], *, duration_ms: int) -> list[Issue]:
    """歌詞の行ごとの警告（\\pos・表示時間・音源の長さ・重なり）。events は Dialogue 行。"""
    issues: list[Issue] = []
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


def starts_drawing(block: str) -> bool | None:
    """上書きタグのブロックの後が図形（\\p）か。\\p が無ければ None（それまでのまま）。"""
    modes = DRAWING_TAG.findall(block)
    return int(modes[-1]) != 0 if modes else None


def text_without_drawings(text: str) -> str:
    """上書きタグと、図形（\\p）の部分を除いた文字。

    1つの行に図形と文字が混ざっていても（`{\\p1}m 0 0 l 1 1{\\p0}歌詞`）、文字だけを取り出す。
    """
    kept: list[str] = []
    drawing = False
    end = 0
    for block in OVERRIDE_BLOCK.finditer(text):
        if not drawing:
            kept.append(text[end : block.start()])
        mode = starts_drawing(block.group())
        if mode is not None:
            drawing = mode
        end = block.end()
    if not drawing:
        kept.append(text[end:])
    return "".join(kept)


def describe(event: pysubs2.SSAEvent) -> str:
    text = OVERRIDE_BLOCK.sub("", event.text).replace("\\N", " ").replace("\\n", " ")
    if len(text) > 20:
        text = text[:20] + "…"
    return f"{pysubs2.time.ms_to_str(event.start, fractions=True)}「{text}」"


def fades_in_at_zero(text: str) -> bool:
    """\\fad・\\fade で、行の始まりにフェードインの途中（またはその前）の状態になるか。

    \\fad(イン,アウト) はイン > 0 のとき。\\fade(a1,a2,a3,t1,t2,t3,t4) は、t2 までに不透明度が
    a1 から a2 へ変わるので、t2 > 0 かつ a1 ≠ a2 のとき。読めない引数の行は対象にしない。
    """
    for raw in _FADE_ARGS.findall(text):
        try:
            args = [float(arg) for arg in raw.split(",")]
        except ValueError:
            continue
        if len(args) == 2 and args[0] > 0:
            return True
        if len(args) == 7 and args[4] > 0 and args[0] != args[1]:
            return True
    return False


def lint_still(subs: pysubs2.SSAFile, *, size: tuple[int, int]) -> list[Issue]:
    """1枚の画像に描く .ass の検査。描くのは 0 秒の状態で、音源とは関係しない。

    歌詞の lint にある、音源の長さとの比較・行の重なり・\\pos の警告は、ここでは的外れなので行わない。
    """
    issues = _play_res_issues(subs, size, "サイズ")
    issues += _undefined_style_issues(subs)
    for event in dialogues(subs):
        if event.start > 0 or event.end <= 0:
            # 何行かだけ描かれないときにも気づけるよう、行ごとに出す
            message = (
                f"0 秒に表示されない行は描かれません（0:00:00.00 から始めてください）: {describe(event)}"
            )
            issues.append(Issue("warning", message))
        elif fades_in_at_zero(event.text):
            message = f"\\fad・\\fade のフェードインが終わる前の状態で描かれます: {describe(event)}"
            issues.append(Issue("warning", message))
    return issues


def lint_vertical(subs: pysubs2.SSAFile, *, size: tuple[int, int], overlay: OverlayText) -> list[Issue]:
    """縦用 .ass のファイル全体についての検査。

    縦用 .ass には区間の外の行（本編の写し）も残るので、行ごとの検査はここでは行わない。
    """
    return (
        _play_res_issues(subs, size, "縦の解像度（vertical.size）")
        + _overlay_style_issues(subs, overlay)
        + _undefined_style_issues(subs)
    )


# 曲名などを .ass の行に埋めるとき、{ } はタグとして読まれる。libass は \{ \} を括弧そのものとして描く。
# \ に続く N n h はエスケープできないので、間に幅の無い WORD JOINER を挟む
# （docs/verification/20260917-thumbnail.md）
_WORD_JOINER = "\u2060"


def escape_text(text: str) -> str:
    """文字列を、.ass の行でそのまま表示されるように書き換える。改行は \\N にする。"""
    text = re.sub(r"\\(?=[Nnh])", "\\\\" + _WORD_JOINER, text)
    return text.translate({ord("{"): r"\{", ord("}"): r"\}", ord("\r"): None, ord("\n"): r"\N"})
