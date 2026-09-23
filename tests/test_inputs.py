"""inputs の二層判定（size・mtime_ns が一致すれば読まずに済ませる）。ffmpeg は要らない。"""

import json
from pathlib import Path

import pytest

from utavideo import inputs
from utavideo.project import Project, scaffold

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
    (root / "build").mkdir(exist_ok=True)
    (root / "build/main.mp4").write_bytes(b"video")
    return root


def _record_build(project: Path) -> None:
    loaded = Project.load(project)
    record = inputs.record_text(loaded, inputs.with_fonts(inputs.snapshot(loaded), ()))
    loaded.inputs_record.parent.mkdir(parents=True, exist_ok=True)
    loaded.inputs_record.write_text(record, encoding="utf-8")


def test_unchanged_files_are_not_read_again(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """size・mtime_ns が記録と一致するファイルは、中身を読み直さない（issue #78）。"""
    _record_build(project)
    calls: list[Path] = []
    original = inputs._file_digest

    def counting(path: Path) -> str | None:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(inputs, "_file_digest", counting)

    loaded = Project.load(project)
    assert inputs.stale_inputs(loaded) is None
    assert calls == []


def test_resaved_file_with_the_same_content_reads_once_and_is_not_stale(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """size・mtime_ns が変わっても、中身が同じなら stale と見なさない（2段目のフォールバック）。"""
    _record_build(project)
    lyrics = project / "src/lyrics.ass"
    lyrics.write_text(lyrics.read_text(encoding="utf-8"), encoding="utf-8")  # 保存し直しただけ

    calls: list[Path] = []
    original = inputs._file_digest

    def counting(path: Path) -> str | None:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(inputs, "_file_digest", counting)

    loaded = Project.load(project)
    assert inputs.stale_inputs(loaded) is None
    assert calls == [lyrics]


def test_old_format_record_is_ignored(project: Path) -> None:
    """format が古い記録は使わない（移行処理なしで安全に無視される）。"""
    loaded = Project.load(project)
    old_record = {"format": 1, "video": inputs._stamp(loaded.main_output), "inputs": {}}
    loaded.inputs_record.parent.mkdir(parents=True, exist_ok=True)
    loaded.inputs_record.write_text(json.dumps(old_record), encoding="utf-8")

    assert inputs._read_record(loaded) is None
