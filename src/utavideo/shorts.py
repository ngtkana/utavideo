"""縦型のショートの区間の読み取りと検査。

区間は縦用 .ass のコメント行（スタイル Short、本文がショートの名前）に置き、
utavideo.toml の [[shorts]] と名前でつなぐ。区間の外の行は書き出しにも検査にも使わない。
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pysubs2

from utavideo import subs
from utavideo.config import Focus, Short
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
    """縦だけの文字（帯の曲名など）の行か。

    歌詞は本編の映像に入っているので、縦用 .ass ではこの行だけを描く。
    """
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

    lines は、その区間で画面に出る歌詞の行（本編の .ass のもの）。
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


def draws(event: pysubs2.SSAEvent, sections: Sequence[Section]) -> bool:
    """その区間で画面に描く行か（縦だけの文字で、区間と時刻が重なる）。"""
    return _is_vertical_only(event) and _in_sections(event, sections)


def lines_in_sections(script: pysubs2.SSAFile, sections: Sequence[Section]) -> pysubs2.SSAFile:
    """区間で描く行（Dialogue 行）だけを残した複製。"""
    selected = subs.without_events(script)
    selected.events = [e for e in subs.dialogues(script) if draws(e, sections)]
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


def resolve_focus(short: Short, default_focus: Focus) -> Focus:
    return short.focus or default_focus


def directory(build_dir: Path) -> Path:
    return build_dir / "shorts"


def output_path(build_dir: Path, short: Short, *, wide: bool = False) -> Path:
    # 16:9 版は別のフォルダに置く。<name>-wide.mp4 だと、name = "chorus-wide" のショートとぶつかる
    return (directory(build_dir) / "wide" if wide else directory(build_dir)) / f"{short.name}.mp4"


def work_ass_path(work_dir: Path, short: Short, folder: Literal["", "wide", "frame"] = "") -> Path:
    """描画に使った .ass。folder は 16:9 版が "wide"、blur の真ん中に置く本編が "frame"。"""
    return work_dir.joinpath("shorts", folder, f"{short.name}.ass")
