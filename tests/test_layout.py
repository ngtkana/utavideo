from pathlib import Path

import pysubs2
import pytest

from tests.conftest import MakeFont
from utavideo import layout

# テスト用フォント: "A" の送り幅 600、空白 300、usWinAscent + usWinDescent = 1000
# → フォントサイズ 100 で "A" は 60px、空白は 30px。表示幅は 320 - 10 - 10 = 300px。


def _script(text: str, *, wrap_style: int = 0, margin_l: int = 0, font: str = "Test Sans"):
    return pysubs2.SSAFile.from_string(
        "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                f"WrapStyle: {wrap_style}",
                "PlayResX: 320",
                "PlayResY: 180",
                "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
                "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
                "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                f"Style: Lyrics,{font},100,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
                "0,0,0,0,100,100,0,0,1,0,0,2,10,10,10,1",
                "",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                f"Dialogue: 0,0:00:01.00,0:00:02.00,Lyrics,,{margin_l},0,0,,{text}",
            ]
        ),
        format_="ass",
    )


@pytest.fixture
def lookup(tmp_path: Path, make_font: MakeFont):
    font = make_font(tmp_path / "TestSans.ttf", "Test Sans")
    return lambda name: (font,) if name == "Test Sans" else ()


@pytest.mark.parametrize(
    ("text", "wrap_style", "expected_width"),
    [
        ("AAAAA", 0, None),
        ("AAAAAA", 0, 360),
        ("AAA AAA", 0, None),  # 空白で折り返せる
        ("AAA AAA", 2, 390),  # WrapStyle 2 は自動改行しない
        (r"{\q2}AAA AAA", 0, 390),
        (r"AAAAA\NAAAAA", 0, None),
        (r"{\fad(150,150)}AAAAAA", 0, 360),
        (r"{\pos(10,10)}AAAAAAAAAA", 0, None),  # \pos の行は対象外
    ],
)
def test_overflows(lookup, text: str, wrap_style: int, expected_width: int | None) -> None:
    issues = layout.overflows(_script(text, wrap_style=wrap_style), lookup)
    if expected_width is None:
        assert issues == []
    else:
        assert len(issues) == 1
        assert f"推定 {expected_width}px ＞ 表示幅 300px" in issues[0].message


def test_event_margin_overrides_style(lookup) -> None:
    issues = layout.overflows(_script("AAAA", margin_l=100), lookup)
    assert len(issues) == 1
    assert "表示幅 210px" in issues[0].message


def test_unknown_font_is_skipped(lookup) -> None:
    assert layout.overflows(_script("AAAAAAAAAA", font="Other"), lookup) == []
