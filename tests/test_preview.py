"""utavideo.preview の --watch 判定ロジックと区間の丸め（ffmpeg は要らない）。

実際の書き出し（静止画・動画）は tests/test_render.py で確かめる。--watch の無限ループ自体は
テストせず、変更を検知する部品（watched_files・snapshot）だけを単体で確かめる。
"""

from pathlib import Path

import pytest

from utavideo import preview
from utavideo.errors import UtavideoError
from utavideo.project import Project, scaffold

TOML = """
[song]
title = "テスト"
slug = "test"
[audio]
file = "src/mix/test.wav"
[video]
background = "src/bg/bg.png"
[[layers]]
name = "logo"
file = "src/layers/logo.png"
"""


def _project(tmp_path: Path) -> Project:
    root = tmp_path / "曲"
    scaffold(root, "テスト", "test")
    (root / "utavideo.toml").write_text(TOML, encoding="utf-8")
    return Project.load(root)


def test_watched_files_lists_config_lyrics_background_and_layers(tmp_path: Path) -> None:
    project = _project(tmp_path)
    assert preview.watched_files(project) == (
        project.config_path,
        project.lyrics_path,
        project.background_path,
        project.root / "src/layers/logo.png",
    )


def test_snapshot_is_none_for_files_that_do_not_exist_yet(tmp_path: Path) -> None:
    project = _project(tmp_path)
    snap = preview.snapshot(preview.watched_files(project))
    # scaffold は utavideo.toml・src/lyrics.ass しか作らないので、背景とレイヤーはまだ無い
    assert snap[project.config_path] is not None
    assert snap[project.lyrics_path] is not None
    assert snap[project.background_path] is None
    assert snap[project.root / "src/layers/logo.png"] is None


def test_snapshot_matches_when_nothing_changed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    files = preview.watched_files(project)
    assert preview.snapshot(files) == preview.snapshot(files)


def test_snapshot_changes_when_a_watched_file_is_written(tmp_path: Path) -> None:
    project = _project(tmp_path)
    files = preview.watched_files(project)
    before = preview.snapshot(files)

    project.background_path.parent.mkdir(parents=True, exist_ok=True)
    project.background_path.write_bytes(b"a")
    after_created = preview.snapshot(files)
    assert after_created != before
    assert after_created[project.background_path] is not None

    # 大きさが変われば、mtime の精度に関係なく確実に検知できる
    project.background_path.write_bytes(b"ab")
    after_changed = preview.snapshot(files)
    assert after_changed != after_created


def test_clip_for_rounds_at_and_duration_to_frames() -> None:
    clip = preview.clip_for(0.5, 1.0, fps=10)
    assert (clip.start_frame, clip.end_frame) == (5, 15)
    assert clip.audio_fade_ms == (0, 0)
    assert clip.duration_s(10) == pytest.approx(1.0)


def test_clip_for_rejects_a_span_shorter_than_one_frame() -> None:
    with pytest.raises(UtavideoError):
        preview.clip_for(0.0, 0.02, fps=10)
