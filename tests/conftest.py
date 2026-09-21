import os
import shlex
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

type MakeFont = Callable[[Path, str], Path]


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


def use_fake_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    reply: str,
    to_stderr: bool = False,
    returncode: int = 0,
) -> Path:
    """`-h filter=subtitles` にだけ決まった答えを返す ffmpeg を PATH の先頭に置き、その ffmpeg を返す。

    他の引数は本物に渡すので、libass を調べるコマンドを変えたときにテストが気付く。
    PATH は置き換えずに前に足すので、ここより先へ進むテストでも他のコマンドは見つかる。
    """
    answer = (
        'for a in "$@"; do\n'
        '  if [ "$a" = "filter=subtitles" ]; then\n'
        f"    printf '%s\\n' {shlex.quote(reply)}{' >&2' if to_stderr else ''}\n"
        f"    exit {returncode}\n"
        "  fi\n"
        "done\n"
    )
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    for tool, head in (("ffmpeg", answer), ("ffprobe", "")):
        real = shutil.which(tool)
        rest = f'exec {shlex.quote(real)} "$@"' if real else f'echo "{tool} がありません" >&2\nexit 127'
        path = bin_dir / tool
        path.write_text(f"#!/bin/sh\n{head}{rest}\n", encoding="utf-8")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir / "ffmpeg"
