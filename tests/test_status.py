"""status（git status 風の一覧）。ffmpeg は要らない。"""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import scaffold_named_project
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
    target = inputs.main_target(loaded)
    record = inputs.record_text(target, inputs.with_fonts(inputs.snapshot(target), ()))
    target.record_path.parent.mkdir(parents=True, exist_ok=True)
    target.record_path.write_text(record, encoding="utf-8")


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


NAMED_TOML = """
[song]
title = "曲"
[audio]
file = "src/mix/曲 v1.2.wav"
[video]
background = "src/bg/bg.png"

[[shorts]]
name = "chorus"

[[thumbnails]]
name = "main"
file = "src/thumbnail.ass"
"""


@pytest.fixture
def named_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """[[shorts]]・[[thumbnails]] を持つ曲フォルダ。"""
    return scaffold_named_project(tmp_path, monkeypatch, NAMED_TOML)


def _record_shorts_build(project: Path) -> None:
    loaded = Project.load(project)
    short = loaded.config.shorts[0]
    target = inputs.shorts_target(loaded, short)
    target.output.parent.mkdir(parents=True, exist_ok=True)
    target.output.write_bytes(b"video")
    record = inputs.record_text(target, inputs.snapshot(target))
    target.record_path.parent.mkdir(parents=True, exist_ok=True)
    target.record_path.write_text(record, encoding="utf-8")


def _record_thumbnail_build(project: Path) -> None:
    loaded = Project.load(project)
    thumb = loaded.config.thumbnails[0]
    target = inputs.thumbnail_target(loaded, thumb)
    target.output.parent.mkdir(parents=True, exist_ok=True)
    target.output.write_bytes(b"png")
    record = inputs.record_text(target, inputs.snapshot(target))
    target.record_path.parent.mkdir(parents=True, exist_ok=True)
    target.record_path.write_text(record, encoding="utf-8")


def test_no_shorts_or_thumbnails_shows_nothing(project: Path) -> None:
    """[[shorts]]・[[thumbnails]] が無い曲フォルダでは該当行が一切出ない。"""
    output = _status(project)
    assert "ショート" not in output
    assert "サムネイル" not in output


def test_shorts_and_thumbnails_show_not_generated(named_project: Path) -> None:
    output = _status(named_project)
    assert "ショート chorus: 未生成です（utavideo shorts --name chorus で" in output
    assert "サムネイル main: 未生成です（utavideo thumbnail --name main で" in output


def test_recorded_shorts_and_thumbnails_are_clean(named_project: Path) -> None:
    _record_shorts_build(named_project)
    _record_thumbnail_build(named_project)

    output = _status(named_project)
    assert "ショート" not in output
    assert "サムネイル" not in output


def test_editing_vertical_ass_marks_only_the_short_stale(named_project: Path) -> None:
    _record_shorts_build(named_project)
    _record_thumbnail_build(named_project)
    (named_project / "src/vertical.ass").write_text("変えた", encoding="utf-8")

    output = _status(named_project)
    assert "ショート chorus:" in output and "vertical.lyrics" in output
    assert "サムネイル" not in output  # thumbnail は vertical.ass に依存しない


def test_editing_thumbnail_ass_marks_only_the_thumbnail_stale(named_project: Path) -> None:
    _record_shorts_build(named_project)
    _record_thumbnail_build(named_project)
    (named_project / "src/thumbnail.ass").write_text("変えた", encoding="utf-8")

    output = _status(named_project)
    assert "サムネイル main:" in output
    assert "ショート" not in output


def test_shorts_config_entry_change_marks_stale_without_editing_files(named_project: Path) -> None:
    _record_shorts_build(named_project)
    _record_thumbnail_build(named_project)
    toml = (named_project / "utavideo.toml").read_text(encoding="utf-8")
    (named_project / "utavideo.toml").write_text(
        toml.replace('name = "chorus"', 'name = "chorus"\nwide = true'), encoding="utf-8"
    )

    output = _status(named_project)
    assert "ショート chorus:" in output and "utavideo.toml" in output
