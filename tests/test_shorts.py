"""ショートの区間の読み取りと検査（ffmpeg を使わない）。"""

import pysubs2

from utavideo import shorts, subs
from utavideo.shorts import Section


def _event(start: float, end: float, text: str, style: str = "Lyrics", *, comment: bool = False):
    return pysubs2.SSAEvent(
        start=round(start * 1000),
        end=round(end * 1000),
        text=text,
        style=style,
        type="Comment" if comment else "Dialogue",
    )


def _short(start: float, end: float, name: str, *, comment: bool = True):
    return _event(start, end, name, "Short", comment=comment)


def _script(*events: pysubs2.SSAEvent) -> pysubs2.SSAFile:
    script = pysubs2.SSAFile()
    script.events = list(events)
    return script


def _messages(issues: list[subs.Issue], level: str) -> list[str]:
    return [i.message for i in issues if i.level == level]


def test_section_is_read_from_the_comment_line_with_surrounding_spaces_removed() -> None:
    script = _script(_short(65.2, 105.65, "  chorus "), _event(65.2, 69.8, "歌詞"))
    found = shorts.check_sections(script, ["chorus"], duration_ms=200_000)
    assert found.issues == []
    assert found.sections == [Section("chorus", 65_200, 105_650)]


def test_missing_and_duplicated_sections_are_errors() -> None:
    script = _script(_short(1, 2, "intro"), _short(3, 4, "intro"))
    found = shorts.check_sections(script, ["chorus", "intro"], duration_ms=10_000)
    errors = _messages(found.issues, "error")
    assert len(errors) == 2
    assert errors[0].startswith("ショート chorus: 区間の行") and "ありません" in errors[0]
    assert errors[1].startswith("ショート intro: 区間の行が 2 個あります")
    assert found.sections == []


def test_name_is_compared_exactly() -> None:
    script = _script(_short(1, 2, "Chorus"))
    found = shorts.check_sections(script, ["chorus"], duration_ms=10_000)
    assert len(_messages(found.issues, "error")) == 1
    assert "合わない区間の行" in _messages(found.issues, "warning")[0]


def test_short_line_left_as_dialogue_is_an_error_but_still_found() -> None:
    script = _script(_short(1, 2, "chorus", comment=False))
    found = shorts.check_sections(script, ["chorus"], duration_ms=10_000)
    errors = _messages(found.issues, "error")
    assert len(errors) == 1
    assert "Dialogue なので、画面に出てしまいます" in errors[0]


def test_unused_section_lines_are_warned() -> None:
    script = _script(_short(1, 2, "chorus"), _short(3, 4, "old"))
    found = shorts.check_sections(script, ["chorus"], duration_ms=10_000)
    warnings = _messages(found.issues, "warning")
    assert len(warnings) == 1 and "0:00:03.000「old」" in warnings[0]


def test_section_length_and_audio_duration() -> None:
    script = _script(_short(5, 5, "empty"), _short(8, 12, "late"), _short(8, 10, "fits"))
    names = ["empty", "late", "fits"]
    found = shorts.check_sections(script, names, duration_ms=10_000)
    errors = _messages(found.issues, "error")
    assert len(errors) == 2
    assert "ショート empty: 区間の終わりが始まり以前です" in errors[0]
    assert (
        "ショート late: 区間（0:00:08.000〜0:00:12.000）が音源の長さ（0:00:10.000）を超えています"
        in errors[1]
    )
    assert [section.name for section in found.sections] == ["fits"]

    unknown = shorts.check_sections(script, names, duration_ms=None)
    assert len(_messages(unknown.issues, "error")) == 1  # 音源の長さが分からなければ、長さとは比べない


def test_edges_inside_a_lyric_line_are_warned() -> None:
    script = _script(
        _short(2, 6, "chorus"),
        _event(1, 3, "頭にかかる"),
        _event(3, 5, "中の行"),
        _event(5, 7, "終わりにかかる"),
        _event(6, 8, "終わりから始まる"),
        # 縦だけの文字と、コメント行は歌詞として見ない
        _event(0, 10, "帯", "VerticalBand"),
        _event(1, 3, "消した行", comment=True),
    )
    issues = shorts.edge_issues(shorts.lyric_lines(script), Section("chorus", 2000, 6000))
    warnings = _messages(issues, "warning")
    assert len(warnings) == 2
    assert warnings[0].startswith("区間の頭（0:00:02.000）が歌詞の行の途中にかかっています")
    assert "0:00:01.000「頭にかかる」（0:00:03.000 まで）" in warnings[0]
    assert "区間の終わり（0:00:06.000）" in warnings[1] and "終わりにかかる" in warnings[1]


def test_lines_in_sections_keeps_only_vertical_only_drawn_lines_that_overlap_a_section() -> None:
    script = _script(
        _short(2, 4, "a"),
        _short(8, 9, "b"),
        _event(0, 2, "直前で終わる"),
        _event(1, 3, "a にかかる"),
        _event(3, 5, "帯", "VerticalBand"),
        _event(3, 4, "コメント", comment=True),
        _event(5, 7, "区間の間"),
        _event(8.5, 9.5, "b にかかる"),
    )
    sections = [Section("a", 2000, 4000), Section("b", 8000, 9000)]
    # 歌詞は本編の映像に入っているので、縦だけの文字（帯）だけを描く
    selected = shorts.lines_in_sections(script, sections)
    assert [e.text for e in selected.events] == ["帯"]
    assert len(script.events) == 8  # 元のスクリプトは変えない


def test_short_lines_in_the_main_lyrics_are_warned() -> None:
    assert shorts.main_lyrics_issues(_script(_event(1, 2, "歌詞"))) == []
    issues = shorts.main_lyrics_issues(_script(_short(1, 2, "chorus")))
    assert len(_messages(issues, "warning")) == 1
    assert "縦用 .ass（vertical.lyrics）に書きます" in issues[0].message


def _render_issues(
    start: float,
    end: float,
    *,
    fps: int = 30,
    duration_ms: int | None = 200_000,
    audio_fade_ms: tuple[int, int] = (300, 1000),
    wide: bool = False,
) -> list[subs.Issue]:
    section = Section("chorus", round(start * 1000), round(end * 1000))
    return shorts.render_issues(
        section, fps=fps, duration_ms=duration_ms, audio_fade_ms=audio_fade_ms, wide=wide
    )


def test_section_edges_are_rounded_to_frames() -> None:
    # 1:05.21 は 30fps では 1956.3 フレーム目なので、1956 フレーム（1:05.200）に丸める
    assert shorts.clip_frames(Section("chorus", 65_210, 105_650), 30) == (1956, 3170)
    assert shorts.clip_frames(Section("chorus", 65_210, 105_650), 10) == (652, 1057)  # 1056.5 は後ろへ


def test_section_shorter_than_a_frame_is_an_error() -> None:
    assert _messages(_render_issues(10.0, 10.01), "error") == [
        "区間がフレームに丸めると長さ 0 になります（30 fps で1フレームより短い）"
    ]


def test_rounding_past_the_audio_is_an_error() -> None:
    # 区間の終わり 9.99 秒は音源（9.99 秒）に収まるが、フレームに丸めると 10.0 秒で超える
    assert _messages(_render_issues(1.0, 9.99, duration_ms=9_990), "error") == [
        "区間の終わりをフレームに丸めた 0:00:10.000 が、音源の長さ（0:00:09.990）を超えています"
    ]
    assert _render_issues(1.0, 9.99, duration_ms=None) == []


def test_fades_longer_than_the_section_are_an_error() -> None:
    assert _messages(_render_issues(1.0, 2.2), "error") == [
        "音声のフェード（vertical.audio_fade_ms の 300 + 1000 ミリ秒）が、"
        "区間の長さ（0:00:01.200）を超えています"
        "（区間を長くするか、vertical.audio_fade_ms を短くする）"
    ]
    assert _render_issues(1.0, 2.3) == []


def test_section_length_is_rounded_once() -> None:
    # 30fps の 1 フレームは 33.33 ミリ秒。両端を別々に丸めて引くと 34 ミリ秒になってしまう
    length = "区間の長さ（0:00:00.033）"
    assert length in _messages(_render_issues(1 / 30, 2 / 30, audio_fade_ms=(0, 34)), "error")[0]


def test_sections_longer_than_the_upload_limits_are_warnings() -> None:
    assert _render_issues(0, 180) == []
    assert _messages(_render_issues(0, 180.1), "warning") == [
        "区間の長さ（0:03:00.100）が、YouTube のショートの上限（180 秒）を超えています"
    ]
    # wide の版は X の通常のアカウントの上限でも見る
    assert len(_messages(_render_issues(0, 150, wide=True), "warning")) == 1
    assert len(_messages(_render_issues(0, 190, wide=True), "warning")) == 2


def test_unused_sections_are_not_reported_when_the_name_is_selected() -> None:
    script = _script(_short(1, 2, "chorus"), _short(3, 4, "intro"))
    assert _messages(shorts.check_sections(script, ["chorus"], duration_ms=10_000).issues, "warning")
    found = shorts.check_sections(script, ["chorus"], duration_ms=10_000, report_unused=False)
    assert found.issues == []
