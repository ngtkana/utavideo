import pysubs2
import pytest

from utavideo import subs
from utavideo.config import ConfigError, OverlayText, Song

SONG = Song(title="曲", artist="歌手", label="ラベル")
OVERLAY = OverlayText()


def _style(name: str, font: str = "Noto Sans JP") -> str:
    return (
        f"Style: {name},{font},64,&H00FFFFFF,&H000000FF,&H00403030,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,4,0,2,120,120,80,1"
    )


def _make(events: list[str], *, styles: list[str] | None = None, play_res: str = "1920x1080"):
    width, height = play_res.split("x")
    style_lines = styles if styles is not None else [_style("Lyrics"), _style("Title")]
    text = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            *style_lines,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
        ]
    )
    return pysubs2.SSAFile.from_string(text, format_="ass")


def _line(start: str, end: str, text: str, style: str = "Lyrics") -> str:
    return f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}"


def _messages(issues: list[subs.Issue], level: str) -> list[str]:
    return [i.message for i in issues if i.level == level]


def test_add_fades_only_where_missing() -> None:
    script = _make(
        [
            _line("0:00:01.00", "0:00:02.00", "あ"),
            _line("0:00:02.00", "0:00:03.00", r"{\fad(10,10)}い"),
            _line("0:00:03.00", "0:00:04.00", r"{\i1}う"),
        ]
    )
    subs.add_fades(script, (150, 150))
    assert [e.text for e in script.events] == [
        r"{\fad(150,150)}あ",
        r"{\fad(10,10)}い",
        r"{\fad(150,150)\i1}う",
    ]


def test_compose_keeps_source_and_appends_overlay() -> None:
    lyrics = _make([_line("0:00:01.00", "0:00:02.00", "あ")])
    script = subs.compose(
        lyrics, song=SONG, overlay=OVERLAY, fade_ms=(100, 100), duration_ms=5000, include_lyrics=True
    )

    assert lyrics.events[0].text == "あ"
    assert script.events[0].text == r"{\fad(100,100)}あ"
    overlay = script.events[-1]
    assert (overlay.start, overlay.end, overlay.style) == (0, 5000, "Title")
    assert overlay.layer == subs.OVERLAY_LAYER
    assert overlay.text == "曲 / 歌手"


def test_overlay_text_can_put_label_on_its_own_line() -> None:
    assert subs.format_overlay_text(r"{label}\N{title} / {artist}", SONG) == r"ラベル\N曲 / 歌手"


def test_compose_preview_has_only_overlay() -> None:
    lyrics = _make([_line("0:00:01.00", "0:00:02.00", "あ")])
    script = subs.compose(
        lyrics, song=SONG, overlay=OVERLAY, fade_ms=(100, 100), duration_ms=5000, include_lyrics=False
    )
    assert [e.style for e in script.events] == ["Title"]
    assert set(script.styles) == {"Lyrics", "Title"}


def test_overlay_text_rejects_unknown_placeholder() -> None:
    with pytest.raises(ConfigError, match="title, artist, label"):
        subs.format_overlay_text("{composer}", SONG)


def test_used_fonts_from_used_styles_and_fn_tags() -> None:
    script = _make(
        [_line("0:00:01.00", "0:00:02.00", r"{\fn@縦書き}あ{\fnYu Gothic}い")],
        styles=[_style("Lyrics", "Noto Sans JP"), _style("Unused", "Unused Font")],
    )
    assert subs.used_fonts(script) == {"Noto Sans JP", "縦書き", "Yu Gothic"}


def test_used_fonts_follows_style_reset_tag() -> None:
    script = _make(
        [_line("0:00:01.00", "0:00:02.00", r"あ{\rTitle}い")],
        styles=[_style("Lyrics", "Noto Sans JP"), _style("Title", "Yu Mincho")],
    )
    assert subs.used_fonts(script) == {"Noto Sans JP", "Yu Mincho"}


def test_lint_clean_script_has_no_issues() -> None:
    script = _make([_line("0:00:01.00", "0:00:02.00", "あ"), _line("0:00:02.00", "0:00:03.00", "い")])
    assert subs.lint(script, size=(1920, 1080), duration_ms=10_000, overlay=OVERLAY) == []


def test_lint_errors() -> None:
    script = _make(
        [_line("0:00:01.00", "0:00:02.00", "あ", style="Typo")],
        styles=[_style("Lyrics")],
        play_res="1280x720",
    )
    errors = _messages(subs.lint(script, size=(1920, 1080), duration_ms=10_000, overlay=OVERLAY), "error")
    assert any("PlayRes 1280x720" in m for m in errors)
    assert any("'Typo'" in m for m in errors)
    assert any("overlay_text.style" in m for m in errors)


def test_lint_reports_misspelled_style_reset_tag() -> None:
    script = _make([_line("0:00:01.00", "0:00:02.00", r"あ{\rTitel}い")])
    errors = _messages(subs.lint(script, size=(1920, 1080), duration_ms=10_000, overlay=OVERLAY), "error")
    assert any("'Titel'" in m for m in errors)


def test_lint_warnings() -> None:
    script = _make(
        [
            _line("0:00:01.00", "0:00:05.00", "長い行"),
            _line("0:00:02.00", "0:00:03.00", "重なる行"),
            _line("0:00:02.00", "0:00:03.00", r"{\pos(100,100)}位置指定"),
            _line("0:00:09.00", "0:00:12.00", "終わりを跨ぐ行"),
            _line("0:00:20.00", "0:00:21.00", "音声の後"),
        ]
    )
    warnings = _messages(subs.lint(script, size=(1920, 1080), duration_ms=10_000, overlay=OVERLAY), "warning")
    assert any("重なっています" in m and "長い行" in m and "重なる行" in m for m in warnings)
    assert any("1 行で \\pos" in m for m in warnings)
    assert any("音声が終わった後" in m for m in warnings)
    assert any("途中で切られます" in m and "終わりを跨ぐ行" in m for m in warnings)
    assert not any("位置指定" in m and "重なって" in m for m in warnings)


def test_lint_still_checks_what_is_drawn_at_zero() -> None:
    script = _make(
        [
            _line("0:00:00.00", "9:59:59.99", r"{\pos(10,10)}曲名", style="Title"),
            _line("0:00:00.00", "9:59:59.99", "重なっても警告しない", style="Title"),
            _line("0:00:01.00", "9:59:59.99", "後から始まる"),
            _line("0:00:00.00", "0:00:00.00", "長さ 0"),
            _line("0:00:00.00", "9:59:59.99", r"{\fad(150,0)}フェードイン"),
            _line("0:00:00.00", "9:59:59.99", r"{\fad(0,150)}フェードアウトだけ"),
            _line("0:00:00.00", "9:59:59.99", "未定義", style="Nope"),
        ],
        play_res="1080x1080",
    )
    issues = subs.lint_still(script, size=(1080, 1080))
    assert _messages(issues, "error") == ["未定義のスタイル 'Nope' を使っている行があります"]
    warnings = _messages(issues, "warning")
    assert len(warnings) == 3
    assert "後から始まる" in warnings[0] and "長さ 0" in warnings[1]
    assert "フェードイン" in warnings[2]


def test_lint_still_compares_play_res_with_size() -> None:
    issues = subs.lint_still(_make([]), size=(1080, 1080))
    assert _messages(issues, "error") == ["PlayRes 1920x1080 がサイズ 1080x1080 と一致しません"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (r"{\fad(150,0)}あ", True),
        (r"{\fad(0,150)}あ", False),
        (r"{\fade(255,0,0,0,150,1000,2000)}あ", True),
        (r"{\fade(255,0,0,-100,-50,1000,2000)}あ", False),  # 0 秒より前にフェードインが終わる
        (r"{\fade(0,0,255,0,150,1000,2000)}あ", False),  # 不透明度が変わらない
        (r"{\fad(x,0)}あ", False),
        ("あ", False),
    ],
)
def test_fades_in_at_zero(text: str, expected: bool) -> None:
    assert subs.fades_in_at_zero(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("曲名 / Artist", "曲名 / Artist"),
        ("{a}", r"\{a\}"),
        (r"a\Nb", "a\\⁠Nb"),
        (r"a\b", r"a\b"),
        (r"a\{b", r"a\\{b"),
        ("1行目\r\n2行目", r"1行目\N2行目"),
    ],
)
def test_escape_text(text: str, expected: str) -> None:
    assert subs.escape_text(text) == expected


@pytest.mark.parametrize(
    ("layout_res", "errors"),
    [
        ("", 0),
        ("LayoutResX: 1920\nLayoutResY: 1080\n", 0),
        # 縦横比が同じなら文字は潰れない（4K の下敷きで Aegisub が書いたときなど）
        ("LayoutResX: 3840\nLayoutResY: 2160\n", 0),
        # libass は片方だけの LayoutRes を使わない（docs/verification/20260917-vertical-ass.md）
        ("LayoutResX: 1080\n", 0),
        ("LayoutResX: 1080\nLayoutResY: 1920\n", 1),
    ],
)
def test_layout_res_with_another_aspect_ratio_is_an_error(layout_res: str, errors: int) -> None:
    script = _make([_line("0:00:01.00", "0:00:02.00", "あ")])
    for line in layout_res.splitlines():
        key, value = line.split(": ")
        script.info[key] = value
    for issues in (
        subs.lint(script, size=(1920, 1080), duration_ms=10_000, overlay=OVERLAY),
        subs.lint_still(script, size=(1920, 1080)),
    ):
        assert len([m for m in _messages(issues, "error") if "LayoutRes" in m]) == errors


def test_lint_vertical_checks_the_whole_file_but_not_each_line() -> None:
    script = _make(
        [
            _line("0:00:01.00", "0:00:05.00", r"{\pos(10,10)}行ごとの検査は区間に入る行だけで行う"),
            _line("0:00:02.00", "0:00:03.00", "重なる行"),
            _line("0:00:02.00", "0:00:03.00", "未定義", style="Nope"),
        ],
        styles=[_style("Lyrics")],
    )
    script.info["LayoutResX"], script.info["LayoutResY"] = "1920", "1080"
    issues = subs.lint_vertical(script, size=(1080, 1920), overlay=OVERLAY)
    assert _messages(issues, "warning") == []
    errors = _messages(issues, "error")
    assert len(errors) == 3
    assert "PlayRes 1920x1080 が縦の解像度（vertical.size） 1080x1920" in errors[0]
    assert "overlay_text.style" in errors[1]
    assert "'Nope'" in errors[2]
