import os
import shlex
import shutil
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
