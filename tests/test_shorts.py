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


def test_lines_in_sections_keeps_drawn_lines_that_overlap_a_section() -> None:
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
    selected = shorts.lines_in_sections(script, sections)
    assert [e.text for e in selected.events] == ["a にかかる", "帯", "b にかかる"]
    assert len(script.events) == 8  # 元のスクリプトは変えない
    # blur では歌詞が本編の映像に入っているので、縦だけの文字だけを描く
    blurred = shorts.lines_in_sections(script, sections, vertical_only=True)
    assert [e.text for e in blurred.events] == ["帯"]


def test_short_lines_in_the_main_lyrics_are_warned() -> None:
    assert shorts.main_lyrics_issues(_script(_event(1, 2, "歌詞"))) == []
    issues = shorts.main_lyrics_issues(_script(_short(1, 2, "chorus")))
    assert len(_messages(issues, "warning")) == 1
    assert "縦用 .ass（vertical.lyrics）に書きます" in issues[0].message


# 本編との突き合わせ。区間は 0〜100 秒で、特に断らなければすべての行が区間に入る
_WHOLE = [Section("chorus", 0, 100_000)]


def _match(main: list[pysubs2.SSAEvent], vertical: list[pysubs2.SSAEvent], sections=_WHOLE) -> list[str]:
    issues = shorts.match_lyrics(_script(*main), _script(*vertical), sections)
    assert all(i.level == "warning" for i in issues)
    return [i.message for i in issues]


def _main_lines() -> list[pysubs2.SSAEvent]:
    return [_event(1, 3, "一行目の歌詞"), _event(4, 6, "二行目の歌詞"), _event(7, 9, "三行目")]


def test_matching_copy_has_no_warnings() -> None:
    vertical = [
        _short(0, 10, "chorus"),
        *_main_lines(),
        # 縦だけの文字は比べない
        _event(0, 10, "フルは関連動画から", "VerticalBand"),
    ]
    assert _match(_main_lines(), vertical) == []


def test_typo_fixed_only_in_the_main_lyrics_is_warned() -> None:
    main = _main_lines()
    main[1].text = "二行目の歌詩"
    messages = _match(main, _main_lines())
    assert messages == [
        "本編と文字が違います（0:00:04.000）: 本編「二行目の歌詩」、縦用 .ass「二行目の歌詞」"
    ]


def test_line_added_to_the_main_lyrics_is_warned() -> None:
    main = [*_main_lines(), _event(10, 12, "足した行")]
    messages = _match(main, _main_lines())
    assert len(messages) == 1
    assert messages[0].startswith("本編の行に対応する縦用 .ass の行がありません: 0:00:10.000「足した行」")


def test_line_removed_from_the_main_lyrics_is_warned() -> None:
    # 行の間が空いていれば、割り当て先の無い縦の行になる
    main = _main_lines()
    del main[1]
    assert _match(main, _main_lines()) == ["本編に時刻の重なる行がありません: 0:00:04.000「二行目の歌詞」"]

    # 隣の行と重なっていれば、隣の行の文字の食い違いになる
    main = [_event(1, 4.5, "一行目の歌詞"), _event(4.5, 6, "二行目の歌詞")]
    vertical = [_event(1, 4.5, "一行目の歌詞"), _event(4.5, 6, "二行目の歌詞")]
    main_removed = [_event(1, 6, "一行目の歌詞")]
    messages = _match(main_removed, vertical)
    assert messages == [
        "本編と文字が違います（0:00:01.000）: 本編「一行目の歌詞」、縦用 .ass「一行目の歌詞二行目の歌詞」"
    ]
    assert _match(main, vertical) == []


def test_time_change_in_the_main_lyrics_is_warned_even_when_pairs_do_not_change() -> None:
    main = _main_lines()
    main[1].start += 300
    main[1].end += 300
    messages = _match(main, _main_lines())
    assert messages == [
        "本編と時刻が違います: 本編 0:00:04.300「二行目の歌詞」（0:00:06.300 まで）、"
        "縦用 .ass 0:00:04.000〜0:00:06.000"
    ]


def test_time_difference_up_to_10_ms_is_allowed() -> None:
    main = _main_lines()
    vertical = _main_lines()
    vertical[0].start += 10
    vertical[2].end -= 10
    assert _match(main, vertical) == []
    vertical[0].start += 1
    assert len(_match(main, vertical)) == 1


def test_line_breaks_positions_sizes_and_styles_changed_in_the_vertical_ass_are_not_warned() -> None:
    main = [_event(1, 3, "長い歌詞の {\\i1}一行目{\\i0}を縦では二行に"), _event(4, 6, "二行目　の歌詞")]
    vertical = [
        _event(1, 3, "{\\pos(540,1200)\\fs80}長い歌詞の一行目を\\N縦では\\h二行に", "Lyrics2"),
        _event(4, 6, "二行目\\nの歌詞", "LyricsBig"),
    ]
    assert _match(main, vertical) == []


def test_line_split_into_two_lines_in_the_vertical_ass_is_not_warned() -> None:
    main = [_event(1, 5, "前半の歌詞と後半の歌詞")]
    vertical = [_event(3, 5, "後半の歌詞"), _event(1, 3, "前半の歌詞と")]
    assert _match(main, vertical) == []
    # つなぎ方が違えば警告する
    vertical = [_event(1, 3, "後半の歌詞"), _event(3, 5, "前半の歌詞と")]
    assert len(_match(main, vertical)) == 1


def test_lines_commented_out_in_the_vertical_ass_are_not_warned() -> None:
    vertical = _main_lines()
    vertical[1].type = "Comment"
    vertical[1].text = "{\\pos(540,1200)}二行目の\\N歌詞"  # タグ・改行は変えてよい
    assert _match(_main_lines(), vertical) == []

    # 文字の違うコメント行では、縦で消したとみなさない（本編の Dialogue 行と対にならないため）
    vertical[1].text = "古い歌詞"
    assert len(_match(_main_lines(), vertical)) == 1

    # コメント行は、Dialogue 行と一緒に割り当てられたら比べない
    main = [_event(1, 5, "前半と後半")]
    vertical = [_event(1, 3, "前半と"), _event(3, 5, "後半"), _event(3, 5, "メモ", comment=True)]
    assert _match(main, vertical) == []
    # 本編に行が無いところのコメント行も警告しない
    assert _match([], [_event(1, 2, "メモ", comment=True)]) == []


def test_overlapping_lines_in_the_main_lyrics_are_matched_one_to_one() -> None:
    # Comment スタイルの行・掛け合い・ハモリが歌詞と同じ時刻に重なる
    main = [
        _event(0, 10, "メモ", "Comment"),
        _event(1, 3, "主旋律"),
        _event(1, 3, "ハモリ", "Harmony"),
        _event(2, 4, "掛け合い", "Call"),
    ]
    assert _match(main, main) == []
    # 縦でスタイルを揃えても、文字で組を選ぶ
    vertical = [
        _event(0, 10, "メモ"),
        _event(1, 3, "ハモリ"),
        _event(1, 3, "主旋律"),
        _event(2, 4, "掛け合い"),
    ]
    assert _match(main, vertical) == []
    # 縁取り用に、同じ行をレイヤー違いで重ねる
    layered = [_event(1, 3, "歌詞", "Outline"), _event(1, 3, "歌詞", "Outline")]
    assert _match(layered, layered) == []


def test_tie_prefers_the_main_line_with_text() -> None:
    main = [_event(1, 3, "{\\an8}"), _event(1, 3, "歌詞")]
    assert _match(main, [_event(1, 3, "歌詞を直した", "Other")]) == [
        "本編と文字が違います（0:00:01.000）: 本編「歌詞」、縦用 .ass「歌詞を直した」"
    ]


def test_short_overlap_with_the_next_line_is_not_warned() -> None:
    main = [_event(1, 3.04, "一行目"), _event(3, 5, "二行目")]
    assert _match(main, main) == []


def test_two_main_lines_merged_into_one_vertical_line_are_not_warned() -> None:
    main = [_event(1, 3, "一行目"), _event(3, 5, "二行目")]
    # つないだ文字と時刻の範囲が合えば、改行を変えただけとみなす
    assert _match(main, [_event(1, 5, "一行目二行目")]) == []
    assert _match(main, [_event(1, 5, "一行目\\N二行目", "Lyrics2")]) == []
    # 3行をまとめてもよい
    three = [*main, _event(5, 7, "三行目")]
    assert _match(three, [_event(1, 7, "一行目二行目三行目")]) == []
    # 時刻の範囲が合わなければ、まとめずに1行ずつ比べる
    assert len(_match(main, [_event(1, 4.5, "一行目二行目")])) == 3
    # 文字が違えば、まとめずに1行ずつ比べる
    messages = _match(main, [_event(1, 5, "一行目三行目")])
    assert len(messages) == 3
    assert "本編「一行目」、縦用 .ass「一行目三行目」" in messages[0]
    assert messages[2].startswith("本編の行に対応する縦用 .ass の行がありません: 0:00:03.000「二行目」")


def test_merged_vertical_line_is_found_from_the_second_main_line() -> None:
    # まとめた縦の行が、重なりの長い2行目に割り当てられても、つないで比べる
    main = [_event(1, 3, "一行目"), _event(2.5, 5, "二行目")]
    assert _match(main, [_event(1, 5, "一行目二行目")]) == []


def test_split_line_is_not_taken_by_the_overlapping_next_main_line() -> None:
    # 前の行を残したまま次の行を出す重ね方で、縦で1行目を2つに分ける
    main = [_event(1, 5, "前半の歌詞後半の歌詞"), _event(3, 7, "次の行")]
    vertical = [_event(1, 3, "前半の歌詞"), _event(3, 5, "後半の歌詞"), _event(3, 7, "次の行")]
    assert _match(main, vertical) == []


def test_empty_dialogue_lines_are_not_used_for_the_time_comparison() -> None:
    main = [_event(1, 3, "歌詞")]
    vertical = [_event(1, 3, "歌詞"), _event(0.5, 3, "{\\an8}")]
    assert _match(main, vertical) == []


def test_vertical_line_without_any_main_line_is_warned() -> None:
    vertical = [*_main_lines(), _event(3.2, 3.8, "縦だけの行", "Lyrics")]
    assert _match(_main_lines(), vertical) == ["本編に時刻の重なる行がありません: 0:00:03.200「縦だけの行」"]


def test_drawing_lines_are_not_compared() -> None:
    main = [*_main_lines(), _event(0, 10, "{\\p1}m 0 0 l 100 0 100 100{\\p0}")]
    vertical = [*_main_lines(), _event(20, 30, "{\\p1}m 0 0 l 50 0 50 50")]
    assert _match(main, vertical) == []


def test_text_next_to_a_drawing_in_the_same_line_is_compared() -> None:
    main = [_event(1, 3, "{\\p1}m 0 0 l 100 0 100 100{\\p0}新しい歌詞")]
    vertical = [_event(1, 3, "{\\p1}m 0 0 l 50 0 50 50{\\p0}古い歌詞")]
    assert _match(main, vertical) == [
        "本編と文字が違います（0:00:01.000）: 本編「新しい歌詞」、縦用 .ass「古い歌詞」"
    ]
    vertical = [_event(1, 3, "{\\p4}m 0 0 l 50 0{\\p0}新しい{\\p1}m 0 0{\\p0}歌詞")]
    assert _match(main, vertical) == []


def test_only_lines_in_sections_are_reported_but_lines_outside_are_used_for_matching() -> None:
    main = [_event(1, 3, "区間の前"), _event(4, 8, "区間の頭をまたぐ行"), _event(20, 22, "区間の後")]
    vertical = [_event(4, 6, "区間の頭を"), _event(6, 8, "またぐ行")]
    sections = [Section("chorus", 7000, 10_000)]
    # 区間の外の本編の行は、対応が無くても警告しない。区間の外の縦の半分も組に入れて比べる
    assert _match(main, vertical, sections) == []
    vertical.append(_event(12, 13, "区間の外の縦だけの行"))
    assert _match(main, vertical, sections) == []


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
