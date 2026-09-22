"""縦型のショートの区間の読み取りと検査。

区間は縦用 .ass のコメント行（スタイル Short、本文がショートの名前）に置き、
utavideo.toml の [[shorts]] と名前でつなぐ。区間の外の行は書き出しにも検査にも使わない。
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pysubs2

from utavideo import subs
from utavideo.config import Focus, Layout, Short
from utavideo.subs import Issue, describe
from utavideo.vertical import SHORT_STYLE, VERTICAL_STYLE_PREFIX


@dataclass(frozen=True)
class Section:
    name: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class SectionCheck:
    issues: list[Issue]
    # 検査を通り、行の検査に使える区間
    sections: list[Section]


def _time(ms: int) -> str:
    # describe と同じ形にして、1つのメッセージに時刻の書き方を混ぜない
    return pysubs2.time.ms_to_str(ms, fractions=True)


def _is_vertical_only(event: pysubs2.SSAEvent) -> bool:
    """縦だけの文字（帯の曲名など）の行か。blur ではこの行だけを描く。"""
    return event.style.startswith(VERTICAL_STYLE_PREFIX)


def _is_lyric_line(event: pysubs2.SSAEvent) -> bool:
    """区間の行と縦だけの文字を除いた、歌詞の行か（Dialogue かどうかは問わない）。"""
    return event.style != SHORT_STYLE and not _is_vertical_only(event)


def check_sections(
    script: pysubs2.SSAFile,
    names: Sequence[str],
    *,
    duration_ms: int | None,
    report_unused: bool = True,
) -> SectionCheck:
    """names の区間を縦用 .ass から探して検査する。

    duration_ms は音源の長さ（分からなければ None で、長さとの比較をしない）。
    report_unused は、どの name にも合わない区間の行を警告するか（名前を絞ったときは警告しない）。
    """
    issues: list[Issue] = []
    lines: dict[str, list[pysubs2.SSAEvent]] = {}
    for event in script.events:
        if event.style != SHORT_STYLE:
            continue
        if event.type != "Comment":
            message = (
                f"スタイル {SHORT_STYLE} の行が Dialogue なので、画面に出てしまいます"
                f"（Aegisub でコメント行にする）: {describe(event)}"
            )
            issues.append(Issue("error", message))
        # Dialogue の行も区間として数える。名前が合っているのに「区間の行が無い」と重ねて出さないため
        lines.setdefault(event.text.strip(), []).append(event)

    sections: list[Section] = []
    for name in names:
        found = lines.get(name, [])
        prefix = f"ショート {name}: "
        if not found:
            message = f"区間の行（スタイル {SHORT_STYLE} のコメント行で、本文が {name}）がありません"
            issues.append(Issue("error", prefix + message))
            continue
        if len(found) > 1:
            where = ", ".join(describe(e) for e in found)
            issues.append(Issue("error", prefix + f"区間の行が {len(found)} 個あります: {where}"))
            continue
        event = found[0]
        section = Section(name, event.start, event.end)
        span = f"（{_time(section.start_ms)}〜{_time(section.end_ms)}）"
        if section.end_ms <= section.start_ms:
            issues.append(Issue("error", prefix + f"区間の終わりが始まり以前です{span}"))
        elif duration_ms is not None and section.end_ms > duration_ms:
            # 音源より後ろの区間でも、ffmpeg は音声の無い・音声の短い動画を正常に書き出してしまう
            message = f"区間{span}が音源の長さ（{_time(duration_ms)}）を超えています"
            issues.append(Issue("error", prefix + message))
        else:
            sections.append(section)

    unused = [e for name, found in lines.items() if name not in names for e in found]
    if unused and report_unused:
        where = ", ".join(describe(e) for e in unused)
        issues.append(Issue("warning", f"どの [[shorts]] の name にも合わない区間の行があります: {where}"))
    return SectionCheck(issues, sections)


def lyric_lines(script: pysubs2.SSAFile) -> list[pysubs2.SSAEvent]:
    """画面に出る歌詞の行（区間の行と縦だけの文字を除いた Dialogue 行）。"""
    return [e for e in subs.dialogues(script) if _is_lyric_line(e)]


def edge_issues(lines: list[pysubs2.SSAEvent], section: Section) -> list[Issue]:
    """区間の頭・終わりが、歌詞の行の途中にかかっているときの警告。

    lines は、その区間で画面に出る歌詞の行（reframe は縦用 .ass、blur は本編の .ass のもの）。
    """
    issues: list[Issue] = []
    for label, at in (("頭", section.start_ms), ("終わり", section.end_ms)):
        for event in lines:
            if event.start < at < event.end:
                message = (
                    f"区間の{label}（{_time(at)}）が歌詞の行の途中にかかっています: "
                    f"{describe(event)}（{_time(event.end)} まで）"
                )
                issues.append(Issue("warning", message))
    return issues


# 投稿先ごとの長さの上限（秒）。区間の長さで判定する（docs/verification/20260918-shorts.md）
SHORT_LIMIT_S = 180  # YouTube のショート
WIDE_LIMIT_S = 140  # X の通常のアカウント


def clip_frames(section: Section, fps: int) -> tuple[int, int]:
    """区間の頭と終わりを、いちばん近いフレームの番号にする。映像・音声・.ass に同じ値を使う。

    Aegisub の時刻はセンチ秒なので、丸めないと映像が音声より最大1フレーム先に進む。
    ちょうど半分のときは後ろのフレームにする（round は偶数側に丸めるので使わない）。
    """
    return _frame(section.start_ms, fps), _frame(section.end_ms, fps)


def _frame(ms: int, fps: int) -> int:
    # pysubs2 の ms_to_frames は round（偶数側に丸める）なので使わない
    return math.floor(ms * fps / 1000 + 0.5)


def render_issues(
    section: Section,
    *,
    fps: int,
    duration_ms: int | None,
    audio_fade_ms: tuple[int, int],
    wide: bool,
) -> list[Issue]:
    """書き出す区間の検査（フレームに丸めた長さ・音源の長さ・フェードの長さ・投稿先の上限）。

    check_sections は Aegisub に書いた時刻で検査するので、フレームに丸めて増える分をここで見る。
    """
    start_frame, end_frame = clip_frames(section, fps)
    if end_frame <= start_frame:
        message = f"区間がフレームに丸めると長さ 0 になります（{fps} fps で1フレームより短い）"
        return [Issue("error", message)]
    end_ms = pysubs2.time.frames_to_ms(end_frame, fps)
    issues: list[Issue] = []
    if duration_ms is not None and end_ms > duration_ms:
        # 区間の終わりが音源より後ろだと、映像より音声の短い動画ができる
        message = (
            f"区間の終わりをフレームに丸めた {_time(end_ms)} が、"
            f"音源の長さ（{_time(duration_ms)}）を超えています"
        )
        issues.append(Issue("error", message))
    # 丸めを1回にして、実際に書き出す長さ（graph.Clip.duration_s）と揃える
    length_ms = pysubs2.time.frames_to_ms(end_frame - start_frame, fps)
    fade_in, fade_out = audio_fade_ms
    if fade_in + fade_out > length_ms:
        message = (
            f"音声のフェード（vertical.audio_fade_ms の {fade_in} + {fade_out} ミリ秒）が、"
            f"区間の長さ（{_time(length_ms)}）を超えています"
            "（区間を長くするか、vertical.audio_fade_ms を短くする）"
        )
        issues.append(Issue("error", message))
    if length_ms > SHORT_LIMIT_S * 1000:
        issues.append(_over_limit(length_ms, "YouTube のショート", SHORT_LIMIT_S))
    if wide and length_ms > WIDE_LIMIT_S * 1000:
        issues.append(_over_limit(length_ms, "X の通常のアカウント", WIDE_LIMIT_S))
    return issues


def _over_limit(length_ms: int, where: str, limit_s: int) -> Issue:
    return Issue(
        "warning", f"区間の長さ（{_time(length_ms)}）が、{where}の上限（{limit_s} 秒）を超えています"
    )


def _in_sections(event: pysubs2.SSAEvent, sections: Sequence[Section]) -> bool:
    return any(event.start < s.end_ms and event.end > s.start_ms for s in sections)


def draws(event: pysubs2.SSAEvent, sections: Sequence[Section], *, vertical_only: bool = False) -> bool:
    """その区間で画面に描く行か（区間と時刻が重なり、区間の行ではない）。

    vertical_only は blur のとき。歌詞は本編の映像に入っているので、縦だけの文字だけを描く。
    """
    drawn = _is_vertical_only(event) if vertical_only else event.style != SHORT_STYLE
    return drawn and _in_sections(event, sections)


def lines_in_sections(
    script: pysubs2.SSAFile, sections: Sequence[Section], *, vertical_only: bool = False
) -> pysubs2.SSAFile:
    """区間で描く行（Dialogue 行）だけを残した複製。"""
    selected = subs.without_events(script)
    selected.events = [e for e in subs.dialogues(script) if draws(e, sections, vertical_only=vertical_only)]
    return selected


def main_lyrics_issues(lyrics: pysubs2.SSAFile) -> list[Issue]:
    """本編の .ass に区間の行を書いてしまったときの警告。"""
    found = [e for e in lyrics.events if e.style == SHORT_STYLE]
    if not found:
        return []
    where = ", ".join(describe(e) for e in found)
    message = (
        f"本編の .ass にスタイル {SHORT_STYLE} の行があります。"
        f"ショートの区間は縦用 .ass（vertical.lyrics）に書きます: {where}"
    )
    return [Issue("warning", message)]


# 本編と縦の時刻の差をここまで許す（Aegisub の時刻はセンチ秒なので、1つ分）
MATCH_TOLERANCE_MS = 10
# 比べるときに除くもの。改行・位置・大きさの変更では何も出さないため
_NOT_TEXT = re.compile(r"\\[Nnh]|\s")


def _plain_text(event: pysubs2.SSAEvent) -> str:
    return _NOT_TEXT.sub("", subs.text_without_drawings(event.text))


def _is_compared(event: pysubs2.SSAEvent) -> bool:
    """突き合わせに使う歌詞の行か。図形（\\p）だけで文字の無い行は比べない。"""
    drawing = any(subs.starts_drawing(block) for block in subs.OVERRIDE_BLOCK.findall(event.text))
    return _is_lyric_line(event) and (not drawing or bool(_plain_text(event)))


def _overlap_ms(a: pysubs2.SSAEvent, b: pysubs2.SSAEvent) -> int:
    return max(0, min(a.end, b.end) - max(a.start, b.start))


@dataclass
class _MainLine:
    event: pysubs2.SSAEvent
    text: str
    assigned: list[pysubs2.SSAEvent] = field(default_factory=list)


def match_lyrics(main: pysubs2.SSAFile, script: pysubs2.SSAFile, sections: Sequence[Section]) -> list[Issue]:
    """区間に入る縦の歌詞が、本編の歌詞と食い違っていないかの警告。

    縦の歌詞の行（コメント行も含む）を、重なる時間がいちばん長い本編の Dialogue 行に割り当て、
    本編の行ごとに、割り当てた行の文字と時刻を比べる。割り当ては区間の外の行も使う
    （区間の端をまたぐ行を、区間の中の片側だけで比べないため）。
    """
    candidates = [_MainLine(e, _plain_text(e)) for e in subs.dialogues(main) if _is_compared(e)]
    found: list[tuple[int, Issue]] = []
    for event in sorted((e for e in script.events if _is_compared(e)), key=lambda e: e.start):
        text = _plain_text(event)
        best = max(
            (c for c in candidates if _overlap_ms(event, c.event) > 0),
            # 重なりが同じなら、文字を含む行 → 文字が同じ行 → 縦の文字を含む行（縦で2つに分けた行の
            # 後半を、時刻の重なる次の行に取られないため） → スタイルが同じ行 → レイヤーが同じ行 →
            # まだ割り当てていない行（縁取り用に同じ行を重ねたとき、1つずつ組にする） → ファイルの先の行
            key=lambda c: (
                _overlap_ms(event, c.event),
                bool(c.text),
                c.text == text,
                text in c.text,
                c.event.style == event.style,
                c.event.layer == event.layer,
                not c.assigned,
            ),
            default=None,
        )
        if best is not None:
            best.assigned.append(event)
        elif event.type == "Dialogue" and text and _in_sections(event, sections):
            message = f"本編に時刻の重なる行がありません: {describe(event)}"
            found.append((event.start, Issue("warning", message)))

    lines = sorted(candidates, key=lambda c: c.event.start)
    start = 0
    while start < len(lines):
        end, issues = _compare_group(lines, start)
        if any(_in_sections(line.event, sections) for line in lines[start:end]):
            found += [(lines[start].event.start, issue) for issue in issues]
        start = end
    return [issue for _, issue in sorted(found, key=lambda item: item[0])]


def _compare_group(lines: Sequence[_MainLine], start: int) -> tuple[int, list[Issue]]:
    """lines[start] から始まる組の終わりと、その組の警告。

    続きの行までつなぐと食い違いが消えるなら、つないだものを1つの組として見る
    （本編の2行を縦で1行にまとめるのは、縦での改行の変え方の1つなので警告しない）。
    """
    single = lines[start : start + 1]
    group = single
    while start + len(group) < len(lines) and _can_extend(group, lines[start + len(group)]):
        group = lines[start : start + len(group) + 1]
        if not _compare(group):
            return start + len(group), []
    return start + 1, _compare(single)


def _can_extend(group: Sequence[_MainLine], following: _MainLine) -> bool:
    """組に続きの行をつないでみる余地があるか。

    まとめた縦の行は、重なりがいちばん長い行に割り当てるので、組のどの行に付くか決まっていない。
    組の文字の続きまで描く行が付いているときと、組には何も付かず、組の頭から始まる行が
    続きの行に付いているときに、つないでみる。
    """
    if _is_partial(group):
        return True
    starts = [e.start for e in _drawn([following])]
    return not _drawn(group) and any(s <= group[0].event.start + MATCH_TOLERANCE_MS for s in starts)


def _main_text(group: Sequence[_MainLine]) -> str:
    return "".join(line.text for line in group)


def _assigned(group: Sequence[_MainLine]) -> list[pysubs2.SSAEvent]:
    """組に割り当てた縦の行。"""
    return [e for line in group for e in line.assigned]


def _drawn(group: Sequence[_MainLine]) -> list[pysubs2.SSAEvent]:
    """組に割り当てた縦の行のうち、画面に文字を描くもの（開始の順）。"""
    drawn = [e for e in _assigned(group) if e.type == "Dialogue" and _plain_text(e)]
    return sorted(drawn, key=lambda e: e.start)


def _vertical_text(drawn: Sequence[pysubs2.SSAEvent]) -> str:
    return "".join(_plain_text(e) for e in drawn)


def _is_partial(group: Sequence[_MainLine]) -> bool:
    """組の文字が、割り当てた縦の行の文字の途中までか（続きの行とつなぐ余地がある）。"""
    text = _main_text(group)
    vertical = _vertical_text(_drawn(group))
    return bool(text) and vertical.startswith(text) and vertical != text


def _compare(group: Sequence[_MainLine]) -> list[Issue]:
    main = group[0].event
    text = _main_text(group)
    drawn = _drawn(group)
    if not drawn:
        if not text:  # 何も描かない行は、縦に無くてよい
            return []
        if any(e.type == "Comment" and _plain_text(e) == text for e in _assigned(group)):
            return []  # 同じ文字のコメント行があれば、縦で意図的に消した行
        message = (
            f"本編の行に対応する縦用 .ass の行がありません: {describe(main)}"
            "（縦で出さないなら、縦用 .ass のこの行を、文字はそのままでコメント行にする）"
        )
        return [Issue("warning", message)]
    issues: list[Issue] = []
    vertical = _vertical_text(drawn)
    if vertical != text:
        message = f"本編と文字が違います（{_time(main.start)}）: 本編「{text}」、縦用 .ass「{vertical}」"
        issues.append(Issue("warning", message))
    main_end = max(line.event.end for line in group)
    start, end = drawn[0].start, max(e.end for e in drawn)
    if abs(start - main.start) > MATCH_TOLERANCE_MS or abs(end - main_end) > MATCH_TOLERANCE_MS:
        message = (
            f"本編と時刻が違います: 本編 {describe(main)}（{_time(main_end)} まで）、"
            f"縦用 .ass {_time(start)}〜{_time(end)}"
        )
        issues.append(Issue("warning", message))
    return issues


def resolve_focus(short: Short, default_focus: Focus) -> Focus:
    return short.focus or default_focus


def resolve_layout(short: Short, default_layout: Layout) -> Layout:
    return short.layout or default_layout


def layouts(targets: Sequence[Short], default_layout: Layout) -> tuple[Layout, ...]:
    """縦用 .ass から実際に描く画面の作り方（[[shorts]] で使うもの）。

    [[shorts]] を書く前（vertical-ass・preview-bg --vertical）は vertical.layout だけになる。
    """
    if not targets:
        return (default_layout,)
    return tuple(dict.fromkeys(resolve_layout(s, default_layout) for s in targets))


def directory(build_dir: Path) -> Path:
    return build_dir / "shorts"


def output_path(build_dir: Path, short: Short, *, wide: bool = False) -> Path:
    # 16:9 版は別のフォルダに置く。<name>-wide.mp4 だと、name = "chorus-wide" のショートとぶつかる
    return (directory(build_dir) / "wide" if wide else directory(build_dir)) / f"{short.name}.mp4"


def work_ass_path(work_dir: Path, short: Short, folder: Literal["", "wide", "frame"] = "") -> Path:
    """描画に使った .ass。folder は 16:9 版が "wide"、blur の真ん中に置く本編が "frame"。"""
    return work_dir.joinpath("shorts", folder, f"{short.name}.ass")
