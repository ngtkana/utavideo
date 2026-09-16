"""release の採番と、公開済みの概要欄の書き直し。動画の中身は問わないので ffmpeg は要らない。"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from utavideo.cli import app
from utavideo.project import scaffold

runner = CliRunner()

TOML = """
[song]
title = "曲"
[audio]
file = "src/mix/曲 v1.2.wav"
[video]
background = "src/bg/bg.png"
"""
DESCRIPTION = '[description]\nhashtags = ["歌ってみた"]\n'


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "20260916 曲"
    scaffold(root, "曲", "曲")
    (root / "utavideo.toml").write_text(TOML, encoding="utf-8")
    (root / "build").mkdir(exist_ok=True)
    (root / "build/main.mp4").write_bytes(b"video")
    return root


def _write_toml(project: Path, text: str) -> None:
    """toml を書き換えたら、build/main.mp4 を新しくする（「入力の方が新しい」で止まらないように）。"""
    (project / "utavideo.toml").write_text(text, encoding="utf-8")
    (project / "build/main.mp4").touch()


def _release(project: Path, *args: str):
    return runner.invoke(app, ["release", "-C", str(project), *args])


def _released(project: Path) -> list[str]:
    return sorted(p.name for p in (project / "release").iterdir())


def test_first_release_starts_at_zero_even_without_release_dir(project: Path) -> None:
    (project / "release").rmdir()
    assert _release(project).exit_code == 0
    assert _released(project) == ["曲-v1.2.0.mp4"]


@pytest.mark.parametrize("version", ["v1", "v1.2.1", "v1.02", "1.2", "v1.2a"])
def test_version_option_takes_only_two_numbers(project: Path, version: str) -> None:
    result = _release(project, "--version", version)
    assert result.exit_code == 1
    assert "vX.Y の形" in result.output


def test_version_option_accepts_uppercase_and_writes_lowercase(project: Path) -> None:
    assert _release(project, "--version", "V2.0").exit_code == 0
    assert _released(project) == ["曲-v2.0.0.mp4"]


def test_stops_when_any_released_video_has_the_same_content(project: Path) -> None:
    # 枝番を手で付けていた頃のファイルと、今の規則の1本目が両方あっても、どちらとも比べる
    (project / "release/曲 v1.2.mp4").write_bytes(b"video")
    (project / "release/曲-v1.2.0.mp4").write_bytes(b"other")

    result = _release(project)
    assert result.exit_code == 1
    assert "曲 v1.2.mp4" in result.output
    assert _released(project) == ["曲 v1.2.mp4", "曲-v1.2.0.mp4"]


def test_stops_when_an_older_number_has_the_same_content(project: Path) -> None:
    (project / "release/曲-v1.2.0.mp4").write_bytes(b"video")
    (project / "release/曲-v1.2.1.mp4").write_bytes(b"other")

    result = _release(project)
    assert result.exit_code == 1
    assert "同じ内容が既にあります" in result.output


def test_counts_uppercase_extension(project: Path) -> None:
    (project / "release/曲-v1.2.3.MP4").write_bytes(b"other")
    assert _release(project).exit_code == 0
    assert "曲-v1.2.4.mp4" in _released(project)


def test_numbers_continue_from_videos_released_before_slug(project: Path) -> None:
    # song.slug より前の名前（曲名と空白区切り）で公開した動画の続きから数える
    (project / "release/曲 v1.2.0.mp4").write_bytes(b"other")
    assert _release(project).exit_code == 0
    assert _released(project) == ["曲 v1.2.0.mp4", "曲-v1.2.1.mp4"]


def test_description_only_rewrites_the_latest_text(project: Path) -> None:
    _write_toml(project, TOML + DESCRIPTION)
    assert _release(project).exit_code == 0
    text = project / "release/曲-v1.2.0.txt"
    assert "#歌ってみた" in text.read_text(encoding="utf-8")

    _write_toml(project, TOML + '[description]\nhashtags = ["歌ってみた", "cover"]\n')
    result = _release(project, "--description-only")
    assert result.exit_code == 0, result.output
    assert "書き直しました" in result.output
    assert "#cover" in text.read_text(encoding="utf-8")
    assert _released(project) == ["曲-v1.2.0.mp4", "曲-v1.2.0.txt"]  # 動画は増えない

    again = _release(project, "--description-only")
    assert again.exit_code == 0
    assert "変わっていません" in again.output


def test_description_only_needs_a_released_video_and_a_description(project: Path) -> None:
    _write_toml(project, TOML + DESCRIPTION)
    missing = _release(project, "--description-only")
    assert missing.exit_code == 1
    assert "公開した動画が release/ にありません" in missing.output

    assert _release(project).exit_code == 0
    _write_toml(project, TOML)
    no_description = _release(project, "--description-only")
    assert no_description.exit_code == 1
    assert "[description] がありません" in no_description.output
