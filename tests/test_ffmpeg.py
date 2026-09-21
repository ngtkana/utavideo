"""ffmpeg の用意ができているかの検査。"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import use_fake_ffmpeg
from utavideo.cli import app
from utavideo.ffmpeg import FFmpegError, require_tools

runner = CliRunner()

# 本物の ffmpeg 6.1 の出力（フィルタがあれば見出し、無ければこの1行で、どちらも終了コードは 0）
HELP = "Filter subtitles\n  Render text subtitles onto input video using the libass library."
UNKNOWN = "Unknown filter 'subtitles'."


def test_require_tools_says_what_to_install_when_ffmpeg_has_no_libass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg = use_fake_ffmpeg(tmp_path, monkeypatch, reply=UNKNOWN)

    with pytest.raises(FFmpegError) as e:
        require_tools()

    assert "libass" in str(e.value)
    assert "ffmpeg-full" in str(e.value)
    assert str(ffmpeg) in str(e.value)  # PATH に別の ffmpeg があるときに、どれを見たか分かるように


def test_require_tools_passes_when_the_subtitles_filter_is_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake_ffmpeg(tmp_path, monkeypatch, reply=HELP)

    require_tools()


def test_require_tools_passes_when_the_help_goes_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 手元の 6.1 は stdout に出すが、stderr に出すビルドで「libass 無し」と誤判定しないこと
    use_fake_ffmpeg(tmp_path, monkeypatch, reply=HELP, to_stderr=True)

    require_tools()


def test_require_tools_reports_a_broken_ffmpeg_instead_of_blaming_libass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = "ffmpeg: error while loading shared libraries: libavfilter.so.9"
    use_fake_ffmpeg(tmp_path, monkeypatch, reply=broken, to_stderr=True, returncode=127)

    with pytest.raises(FFmpegError) as e:
        require_tools()

    assert "libass" not in str(e.value)  # 入れ直す先を間違えないよう、libass のせいにしない
    assert "終了コード 127" in str(e.value)
    assert "libavfilter.so.9" in str(e.value)


def test_require_tools_skips_the_libass_check_when_subtitles_are_not_drawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fake_ffmpeg(tmp_path, monkeypatch, reply=UNKNOWN)

    require_tools(subtitles=False)


def test_build_stops_with_the_same_message_before_it_looks_at_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "song"  # utavideo.toml すら無いので、先に検査していなければ別のエラーになる
    project.mkdir()
    use_fake_ffmpeg(tmp_path, monkeypatch, reply=UNKNOWN)

    result = runner.invoke(app, ["build", "-C", str(project)])

    assert result.exit_code == 1
    assert "libass" in result.output
    assert list(project.iterdir()) == []
