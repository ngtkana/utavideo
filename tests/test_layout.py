from pathlib import Path

import pysubs2
import pytest

from tests.conftest import MakeFont
from utavideo import layout

# テスト用フォント: "A" の送り幅 600、空白 300、usWinAscent + usWinDescent = 1000
# → フォントサイズ 100 で "A" は 60px、空白は 30px。表示幅は 320 - 10 - 10 = 300px。


def _style(name: str = "Lyrics", font: str = "Test Sans", size: int = 100) -> str:
    return (
        f"Style: {name},{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,2,10,10,10,1"
    )


def _script(
    text: str,
    *,
    wrap_style: int = 0,
    margin_l: int = 0,
    font: str = "Test Sans",
    styles: list[str] | None = None,
):
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
                *(styles if styles is not None else [_style(font=font)]),
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
        (r"{\fs200}AAA", 0, 360),  # \fs でサイズを上げた行
        (r"{\fs20}AAAAAAAAAA", 0, None),  # \fs で下げた行は収まる
        (r"AAA{\fs200}AA", 0, 420),  # 行の途中で変わる
        (r"{\fscx200}AAA", 0, 360),
        (r"{\fsp50}AAA", 0, 330),
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


def test_style_reset_tag_switches_size(lookup) -> None:
    styles = [_style(), _style("Small", size=20)]
    assert layout.overflows(_script(r"{\rSmall}AAAAAAAAAA", styles=styles), lookup) == []

    issues = layout.overflows(_script(r"{\rSmall}AAAAA{\r}AAAAA", styles=styles), lookup)
    assert len(issues) == 1
    assert "推定 360px" in issues[0].message


def test_unknown_font_is_skipped(lookup) -> None:
    assert layout.overflows(_script("AAAAAAAAAA", font="Other"), lookup) == []
    assert layout.overflows(_script(r"AAAAAAAAAA{\fnOther}A"), lookup) == []
