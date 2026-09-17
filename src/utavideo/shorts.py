"""縦型のショートの区間の読み取りと検査。

区間は縦用 .ass のコメント行（スタイル Short、本文がショートの名前）に置き、
utavideo.toml の [[shorts]] と名前でつなぐ。区間の外の行は書き出しにも検査にも使わない。
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

import pysubs2

from utavideo import subs
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


def _is_lyric_line(event: pysubs2.SSAEvent) -> bool:
    """区間の行と縦だけの文字を除いた、歌詞の行か（Dialogue かどうかは問わない）。"""
    return event.style != SHORT_STYLE and not event.style.startswith(VERTICAL_STYLE_PREFIX)


def check_sections(script: pysubs2.SSAFile, names: Sequence[str], *, duration_ms: int | None) -> SectionCheck:
    """[[shorts]] のすべての name の区間を縦用 .ass から探して検査する。

    duration_ms は音源の長さ（分からなければ None で、長さとの比較をしない）。
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
    lyric_lines = [e for e in subs.dialogues(script) if _is_lyric_line(e)]
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
            issues += subs.prefixed(_edge_issues(lyric_lines, section), prefix)

    unused = [e for name, found in lines.items() if name not in names for e in found]
    if unused:
        where = ", ".join(describe(e) for e in unused)
        issues.append(Issue("warning", f"どの [[shorts]] の name にも合わない区間の行があります: {where}"))
    return SectionCheck(issues, sections)


def _edge_issues(lyric_lines: list[pysubs2.SSAEvent], section: Section) -> list[Issue]:
    """区間の頭・終わりが、歌詞の行の途中にかかっているときの警告。"""
    issues: list[Issue] = []
    for label, at in (("頭", section.start_ms), ("終わり", section.end_ms)):
        for event in lyric_lines:
            if event.start < at < event.end:
                message = (
                    f"区間の{label}（{_time(at)}）が歌詞の行の途中にかかっています: "
                    f"{describe(event)}（{_time(event.end)} まで）"
                )
                issues.append(Issue("warning", message))
    return issues


def _in_sections(event: pysubs2.SSAEvent, sections: Sequence[Section]) -> bool:
    return any(event.start < s.end_ms and event.end > s.start_ms for s in sections)


def lines_in_sections(script: pysubs2.SSAFile, sections: Sequence[Section]) -> pysubs2.SSAFile:
    """区間と時刻が重なる、描く行（区間の行を除く Dialogue 行）だけを残した複製。"""
    selected = subs.without_events(script)
    selected.events = [
        event
        for event in subs.dialogues(script)
        if event.style != SHORT_STYLE and _in_sections(event, sections)
    ]
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
    return _NOT_TEXT.sub("", subs.OVERRIDE_BLOCK.sub("", event.text))


def _is_compared(event: pysubs2.SSAEvent) -> bool:
    """突き合わせに使う歌詞の行か。図形（\\p）の行は文字が無いので比べない。"""
    drawing = any(subs.DRAWING_TAG.search(block) for block in subs.OVERRIDE_BLOCK.findall(event.text))
    return _is_lyric_line(event) and not drawing


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
    # 開始の順に割り当てるので、本編の行ごとの assigned も開始の順に並ぶ
    for event in sorted((e for e in script.events if _is_compared(e)), key=lambda e: e.start):
        text = _plain_text(event)
        best = max(
            (c for c in candidates if _overlap_ms(event, c.event) > 0),
            # 重なりが同じなら、文字を含む行 → 文字が同じ行 → スタイルが同じ行 → レイヤーが同じ行 →
            # まだ割り当てていない行（縁取り用に同じ行を重ねたとき、1つずつ組にする） → ファイルの先の行
            key=lambda c: (
                _overlap_ms(event, c.event),
                bool(c.text),
                c.text == text,
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

    for line in candidates:
        if _in_sections(line.event, sections):
            found += [(line.event.start, issue) for issue in _compare(line)]
    return [issue for _, issue in sorted(found, key=lambda item: item[0])]


def _compare(line: _MainLine) -> list[Issue]:
    main = line.event
    if not line.assigned:
        if not line.text:  # 何も描かない行は、縦に無くてよい
            return []
        message = (
            f"本編の行に対応する縦用 .ass の行がありません: {describe(main)}"
            "（縦で出さないなら、縦用 .ass のこの時刻にコメント行を置く）"
        )
        return [Issue("warning", message)]
    drawn = [e for e in line.assigned if e.type == "Dialogue"]
    if not drawn:  # すべてコメント行なら、縦で意図的に消した行
        return []
    issues: list[Issue] = []
    text = "".join(_plain_text(e) for e in drawn)
    if text != line.text:
        message = f"本編と文字が違います（{_time(main.start)}）: 本編「{line.text}」、縦用 .ass「{text}」"
        issues.append(Issue("warning", message))
    start, end = drawn[0].start, max(e.end for e in drawn)
    if abs(start - main.start) > MATCH_TOLERANCE_MS or abs(end - main.end) > MATCH_TOLERANCE_MS:
        message = (
            f"本編と時刻が違います: 本編 {describe(main)}（{_time(main.end)} まで）、"
            f"縦用 .ass {_time(start)}〜{_time(end)}"
        )
        issues.append(Issue("warning", message))
    return issues
