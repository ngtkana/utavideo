import os
import shlex
import shutil
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
# console.py は import のときに Console を作るので、CI のように COLUMNS を付けて走らせると、フィクスチャ
# から monkeypatch.setenv しても間に合わない。だから環境変数ではなく、ここで直に、折り返しの起きようが
# ない幅まで広げる。
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


def use_fake_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    reply: str,
    to_stderr: bool = False,
    returncode: int = 0,
    filter: str = "subtitles",
) -> Path:
    """`-h filter=<filter>` にだけ決まった答えを返す ffmpeg を PATH の先頭に置き、その ffmpeg を返す。

    他の引数は本物に渡すので、libass・rubberband を調べるコマンドを変えたときにテストが気付く。
    PATH は置き換えずに前に足すので、ここより先へ進むテストでも他のコマンドは見つかる。
    """
    answer = (
        'for a in "$@"; do\n'
        f'  if [ "$a" = "filter={filter}" ]; then\n'
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
