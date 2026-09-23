"""status（git status 風の一覧）。ffmpeg は要らない。"""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from utavideo import inputs
from utavideo.cli import app
from utavideo.project import Project, scaffold

runner = CliRunner()

TOML = """
[song]
title = "曲"
[audio]
file = "src/mix/曲 v1.2.wav"
[video]
background = "src/bg/bg.png"
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "曲"
    scaffold(root, "曲", "曲")
    (root / "utavideo.toml").write_text(TOML, encoding="utf-8")
    return root


def _record_build(project: Path) -> None:
    """build が書き出し終えたときの記録を、ffmpeg を使わずに作る。"""
    (project / "build").mkdir(exist_ok=True)
    (project / "build/main.mp4").write_bytes(b"video")
    loaded = Project.load(project)
    record = inputs.record_text(loaded, inputs.with_fonts(inputs.snapshot(loaded), ()))
    loaded.inputs_record.parent.mkdir(parents=True, exist_ok=True)
    loaded.inputs_record.write_text(record, encoding="utf-8")


def _edit_later(project: Path, rel: str, text: str) -> None:
    """build/main.mp4 より新しい更新時刻で書く。"""
    path = project / rel
    path.write_text(text, encoding="utf-8")
    later = (project / "build/main.mp4").stat().st_mtime + 10
    os.utime(path, (later, later))


def _status(project: Path) -> str:
    result = runner.invoke(app, ["status", "-C", str(project)])
    assert result.exit_code == 0, result.output
    return result.output


def test_fresh_project_shows_nothing_generated(project: Path) -> None:
    output = _status(project)
    assert "main: 未生成です" in output
    assert "概要欄: 未生成です" in output
    assert "告知文: 未生成です" in output
    assert "release" not in output


def test_clean_when_everything_matches(project: Path) -> None:
    _record_build(project)
    (project / "build/title.txt").write_text("タイトル", encoding="utf-8")
    (project / "build/description.txt").write_text("概要", encoding="utf-8")
    (project / "build/announce.txt").write_text("告知", encoding="utf-8")
    (project / "release").mkdir(exist_ok=True)
    (project / "release/曲-v1.2.0.mp4").write_bytes(b"video")

    assert _status(project) == "クリーンです（差分はありません）\n"


def test_stale_main_blocks_the_release_line(project: Path) -> None:
    _record_build(project)
    lyrics = project / "src/lyrics.ass"
    _edit_later(project, "src/lyrics.ass", lyrics.read_text(encoding="utf-8") + "\n")

    output = _status(project)
    assert "main:" in output and "（lyrics.file）" in output
    assert "release" not in output


def test_not_released_shows_the_next_path(project: Path) -> None:
    _record_build(project)

    assert "release: まだ release していません" in _status(project)
    assert "曲-v1.2.0.mp4" in _status(project)


def test_needs_release_when_main_differs_from_the_released_copy(project: Path) -> None:
    _record_build(project)
    (project / "release").mkdir(exist_ok=True)
    (project / "release/曲-v1.2.0.mp4").write_bytes(b"different content")

    output = _status(project)
    assert "release: 内容が変わっています" in output
    assert "曲-v1.2.1.mp4" in output


def test_writing_the_outputs_clears_the_description_and_announce_lines(project: Path) -> None:
    _record_build(project)
    (project / "build/title.txt").write_text("タイトル", encoding="utf-8")
    (project / "build/description.txt").write_text("概要", encoding="utf-8")

    output = _status(project)
    assert "概要欄" not in output
    assert "告知文: 未生成です" in output
