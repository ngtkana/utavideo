"""ffmpeg の用意ができているかの検査。"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from utavideo.cli import app
from utavideo.ffmpeg import FFmpegError, require_tools

runner = CliRunner()


def _fake_ffmpeg(tmp_path: Path, *, subtitles: bool) -> Path:
    """subtitles フィルタの有無だけを答える偽の ffmpeg / ffprobe を置いた PATH を返す。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    reply = "Filter subtitles" if subtitles else "Unknown filter 'subtitles'."
    # 本物と同じく、フィルタが無くても終了コードは 0
    (bin_dir / "ffmpeg").write_text(f'#!/bin/sh\necho "{reply}"\n', encoding="utf-8")
    (bin_dir / "ffmpeg").chmod(0o755)
    (bin_dir / "ffprobe").write_text("#!/bin/sh\n", encoding="utf-8")
    (bin_dir / "ffprobe").chmod(0o755)
    return bin_dir


def test_require_tools_says_what_to_install_when_ffmpeg_has_no_libass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(_fake_ffmpeg(tmp_path, subtitles=False)))

    with pytest.raises(FFmpegError) as e:
        require_tools()

    assert "libass" in str(e.value)
    assert "ffmpeg-full" in str(e.value)


def test_require_tools_passes_when_the_subtitles_filter_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(_fake_ffmpeg(tmp_path, subtitles=True)))

    require_tools()


def test_build_stops_with_the_same_message_before_it_looks_at_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "song"  # utavideo.toml すら無いので、先に検査していなければ別のエラーになる
    project.mkdir()
    monkeypatch.setenv("PATH", str(_fake_ffmpeg(tmp_path, subtitles=False)))

    result = runner.invoke(app, ["build", "-C", str(project)])

    assert result.exit_code == 1
    assert "libass" in result.output
    assert list(project.iterdir()) == []
