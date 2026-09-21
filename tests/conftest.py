from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from utavideo import cli
from utavideo.cli import app
from utavideo.sample import build_box_font

type MakeFont = Callable[[Path, str], Path]


# 出力を確かめるテストが、端末の幅による折り返しで落ちないようにする。折り返しはパスや語の途中にも
# 入るうえ、折り返し位置が語の切れ目とちょうど重なるとその空白が消える（幅 4 なら "v1.0 のような" が
# "v1.0\nのよ\nうな"）ので、出力を畳み直しても元のメッセージには戻せない。
# rich は COLUMNS が環境にあれば Console を作るときに幅を焼き付ける（無ければ描画のたびに読み直す）。
# cli は import のときに Console を作るので、CI のように COLUMNS を付けて走らせると、フィクスチャから
# monkeypatch.setenv しても間に合わない。だから環境変数ではなく、ここで直に、折り返しの起きようがない
# 幅まで広げる。
# Typer/Click が help・usage 用に自分で作る Console には効かない。必要になったら
# typer.rich_utils.MAX_WIDTH（環境変数 TERMINAL_WIDTH を import のときに読む）を同じように広げる。
cli.console.width = cli.err_console.width = 10**6


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
