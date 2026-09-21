import unicodedata
from pathlib import Path

import pysubs2
import pytest

from utavideo import fonts, subs
from utavideo.config import ConfigError, OverlayText, Song

SONG = Song(title="曲", artist="歌手", label="ラベル")
OVERLAY = OverlayText()
EMPTY_INDEX = fonts.FontIndex({})


def _index_with(*names: str) -> fonts.FontIndex:
    """names のそれぞれを、その表記のまま実際に持つ索引（テスト用）。"""
    return fonts.FontIndex(
        {fonts.match_key(name): fonts.FontMatch((Path(f"/fonts/{name}"),), name) for name in names}
    )


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
        lyrics,
        song=SONG,
        overlay=OVERLAY,
        fade_ms=(100, 100),
        duration_ms=5000,
        include_lyrics=True,
        font_index=EMPTY_INDEX,
    )

    assert lyrics.events[0].text == "あ"
    assert script.events[0].text == r"{\fad(100,100)}あ"
    overlay = script.events[-1]
    assert (overlay.start, overlay.end, overlay.style) == (0, 5000, "Title")
    assert overlay.layer == subs.OVERLAY_LAYER
    assert overlay.text == "曲 / 歌手"


def test_compose_normalizes_font_names_to_the_index_display_name() -> None:
    # libass は .ass の名前とフォント内の名前をそのまま比べる。macOS では NFD の名前が入りやすい。
    # 索引にあるフォントが実際に持つ表記へ揃える（一律 NFC にはしない）
    nfc = unicodedata.normalize("NFC", "テストゴシック")
    nfd = unicodedata.normalize("NFD", nfc)
    lyrics = _make(
        [_line("0:00:01.00", "0:00:02.00", rf"あ{{\fn{nfd}}}い")],
        styles=[_style("Lyrics", nfd), _style("Title", nfd)],
    )
    script = subs.compose(
        lyrics,
        song=SONG,
        overlay=OVERLAY,
        fade_ms=(0, 0),
        duration_ms=5000,
        include_lyrics=True,
        font_index=_index_with(nfc),
    )

    assert script.styles["Lyrics"].fontname == nfc
    assert script.events[0].text == rf"あ{{\fn{nfc}}}い"
    assert subs.used_fonts(script) == {nfc}
    assert lyrics.styles["Lyrics"].fontname == nfd  # 元の .ass は変えない


def test_compose_matches_the_font_files_own_normalization_even_if_it_is_nfd() -> None:
    # フォントファイルの name テーブルが NFD のとき、.ass 側を一律 NFC にすると
    # 逆に不一致になる（索引にある NFD の表記へ揃えるのが正しい）
    nfc = unicodedata.normalize("NFC", "テストゴシック")
    nfd = unicodedata.normalize("NFD", nfc)
    lyrics = _make([_line("0:00:01.00", "0:00:02.00", "あ")], styles=[_style("Lyrics", nfc)])
    script = subs.compose(
        lyrics,
        song=SONG,
        overlay=OVERLAY,
        fade_ms=(0, 0),
        duration_ms=5000,
        include_lyrics=True,
        font_index=_index_with(nfd),
    )

    assert script.styles["Lyrics"].fontname == nfd


def test_compose_normalizes_vertical_font_names_too() -> None:
    # 先頭の @ は縦書き指定で、フォント名そのものではない（used_fonts と同じ扱い）。
    # @ を残したまま、索引にある表記へ揃える
    nfc = unicodedata.normalize("NFC", "テストゴシック")
    nfd = unicodedata.normalize("NFD", nfc)
    lyrics = _make(
        [_line("0:00:01.00", "0:00:02.00", rf"あ{{\fn@{nfd}}}い")],
        styles=[_style("Lyrics", "@" + nfd), _style("Title")],
    )
    script = subs.compose(
        lyrics,
        song=SONG,
        overlay=OVERLAY,
        fade_ms=(0, 0),
        duration_ms=5000,
        include_lyrics=True,
        font_index=_index_with(nfc),
    )

    assert script.styles["Lyrics"].fontname == "@" + nfc
    assert script.events[0].text == rf"あ{{\fn@{nfc}}}い"


def test_compose_leaves_unknown_font_names_untouched() -> None:
    lyrics = _make([_line("0:00:01.00", "0:00:02.00", "あ")], styles=[_style("Lyrics", "無い書体")])
    script = subs.compose(
        lyrics,
        song=SONG,
        overlay=OVERLAY,
        fade_ms=(0, 0),
        duration_ms=5000,
        include_lyrics=True,
        font_index=EMPTY_INDEX,
    )

    assert script.styles["Lyrics"].fontname == "無い書体"


def test_compose_normalizes_the_overlay_text_font_tag_too() -> None:
    # 正規化は overlay のイベントを足した後に行う（曲名表示にも \fn タグを使える）
    nfc = unicodedata.normalize("NFC", "テストゴシック")
    nfd = unicodedata.normalize("NFD", nfc)
    lyrics = _make([_line("0:00:01.00", "0:00:02.00", "あ")])
    # overlay_text.text は str.format を通るので、リテラルの {} は {{ }} で書く
    overlay = OverlayText(text="{{\\fn" + nfd + "}}{title}")
    script = subs.compose(
        lyrics,
        song=SONG,
        overlay=overlay,
        fade_ms=(0, 0),
        duration_ms=5000,
        include_lyrics=True,
        font_index=_index_with(nfc),
    )

    assert script.events[-1].text == rf"{{\fn{nfc}}}曲"


def test_overlay_text_can_put_label_on_its_own_line() -> None:
    assert subs.format_overlay_text(r"{label}\N{title} / {artist}", SONG) == r"ラベル\N曲 / 歌手"


def test_compose_preview_has_only_overlay() -> None:
    lyrics = _make([_line("0:00:01.00", "0:00:02.00", "あ")])
    script = subs.compose(
        lyrics,
        song=SONG,
        overlay=OVERLAY,
        fade_ms=(100, 100),
        duration_ms=5000,
        include_lyrics=False,
        font_index=EMPTY_INDEX,
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
