from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from utavideo.cli import app
from utavideo.sample import build_box_font

type MakeFont = Callable[[Path, str], Path]


@pytest.fixture
def make_font() -> MakeFont:
    """文字 "A" が塗りつぶしの四角になる最小の TrueType フォントを作る。"""

    def make(path: Path, family: str) -> Path:
        return build_box_font(path, family, chars="A", advance=600, space_advance=300)

    return make


def invoke(*args: str):
    """utavideo のコマンドを実行し、成功したことを確かめる。"""
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result
