from collections.abc import Callable
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from utavideo import cli

type MakeFont = Callable[[Path, str], Path]


# 出力を確かめるテストが、端末の幅による折り返しで落ちないようにする。折り返しはパスや語の途中にも
# 入るうえ、空白のところで折り返すとその空白は消える（幅 30 なら "v1.0 のような" が "v1.0\nのような"）
# ので、出力を畳み直しても元のメッセージには戻せない。rich は Console を作るときに幅を決め、cli は
# import のときに Console を作るので、環境変数 COLUMNS ではなく、ここで直に広げる。
cli.console.width = cli.err_console.width = 1000


def _box():
    pen = TTGlyphPen(None)
    pen.moveTo((50, 0))
    pen.lineTo((50, 700))
    pen.lineTo((550, 700))
    pen.lineTo((550, 0))
    pen.closePath()
    return pen.glyph()


@pytest.fixture
def make_font() -> MakeFont:
    """文字 "A" が塗りつぶしの四角になる最小の TrueType フォントを作る。"""

    def make(path: Path, family: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fb = FontBuilder(unitsPerEm=1000, isTTF=True)
        fb.setupGlyphOrder([".notdef", "space", "A"])
        fb.setupCharacterMap({0x20: "space", 0x41: "A"})
        fb.setupGlyf({".notdef": _box(), "space": TTGlyphPen(None).glyph(), "A": _box()})
        fb.setupHorizontalMetrics({".notdef": (600, 0), "space": (300, 0), "A": (600, 0)})
        fb.setupHorizontalHeader(ascent=800, descent=-200)
        fb.setupNameTable({"familyName": family, "styleName": "Regular"})
        fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
        fb.setupPost()
        fb.save(str(path))
        return path

    return make
