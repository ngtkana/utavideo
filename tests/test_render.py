"""ffmpeg を実際に動かす結合テスト。"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import MakeFont
from utavideo import cli
from utavideo.cli import app
from utavideo.project import scaffold

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が必要")

runner = CliRunner()

TOML = """
[song]
title = "テスト"
slug = "test"
artist = "テスター"
[audio]
file = "src/mix/テスト v1.2.wav"
[video]
background = "src/bg/{background}"
size = [320, 180]
fps = 10
preset = "ultrafast"
[overlay_text]
enabled = false
"""

STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
LYRICS = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 320
PlayResY: 180

[V4+ Styles]
{STYLE_FORMAT}
Style: Lyrics,{{font}},40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,10,10,10,1
Style: Title,{{font}},20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,9,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.20,0:00:01.50,Lyrics,,0,0,0,,AAAA
"""


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def _stream(info: dict, kind: str) -> dict:
    return next(s for s in info["streams"] if s["codec_type"] == kind)


def _max_alpha(path: Path, at: float) -> int:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
         "-vf", "alphaextract,format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
        check=True,
    )  # fmt: skip
    return max(out.stdout)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_font: MakeFont) -> Path:
    make_font(tmp_path / "fonts" / "TestSans.ttf", "Test Sans")
    monkeypatch.setenv("UTAVIDEO_FONT_DIRS", str(tmp_path / "fonts"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    # filtergraph のエスケープを確かめるため、記号を含むフォルダ名にする
    root = tmp_path / "20260101 it's [テスト], 曲"
    scaffold(root, "テスト", "test")
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(root / "src/mix/テスト v1.2.wav"))
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=640x360", "-frames:v", "1", str(root / "src/bg/bg.png"))
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=640x360:rate=4:duration=0.5", str(root / "src/bg/loop.gif"))
    (root / "utavideo.toml").write_text(TOML.format(background="bg.png"), encoding="utf-8")
    (root / "src/lyrics.ass").write_text(LYRICS.format(font="Test Sans"), encoding="utf-8")
    return root


def _invoke(*args: str):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result


def test_check_passes(project: Path) -> None:
    output = _invoke("check", "-C", str(project)).output
    assert "問題ありません" in output
    assert "release 先" in output and "test-v1.2.0.mp4" in output  # 次に付く名前


def test_check_counts_warnings_instead_of_saying_ok(project: Path) -> None:
    # 音源は 2 秒。その終わりを跨ぐ行を足す
    lyrics = LYRICS.format(font="Test Sans") + "Dialogue: 0,0:00:01.80,0:00:03.00,Lyrics,,0,0,0,,BBBB\n"
    (project / "src/lyrics.ass").write_text(lyrics, encoding="utf-8")

    output = _invoke("check", "-C", str(project)).output
    assert "問題ありません" not in output
    assert "警告 1 件" in output


def test_check_reports_audio_without_sound(project: Path) -> None:
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc=size=64x36:rate=10:duration=2", "-an",
        str(project / "src/mix/noaudio.mp4"),
    )  # fmt: skip
    config = (project / "utavideo.toml").read_text(encoding="utf-8")
    (project / "utavideo.toml").write_text(
        config.replace('file = "src/mix/テスト v1.2.wav"', 'file = "src/mix/noaudio.mp4"'),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "音声" in result.output


def test_check_reports_missing_font(project: Path) -> None:
    (project / "src/lyrics.ass").write_text(LYRICS.format(font="Nope Sans"), encoding="utf-8")
    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "Nope Sans" in result.output


def test_build_writes_main_mp4(project: Path) -> None:
    _invoke("build", "-C", str(project))

    output = project / "build/main.mp4"
    info = _probe(output)
    video, audio = _stream(info, "video"), _stream(info, "audio")
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 320, 180)
    assert video["color_space"] == "bt709"
    assert (audio["codec_name"], audio["sample_rate"]) == ("aac", "48000")
    assert float(info["format"]["duration"]) == pytest.approx(2.0, abs=0.15)
    assert not (project / "build/main.partial.mp4").exists()


def test_gif_background_loops_for_whole_audio(project: Path) -> None:
    (project / "utavideo.toml").write_text(TOML.format(background="loop.gif"), encoding="utf-8")
    _invoke("build", "-C", str(project))
    video = _stream(_probe(project / "build/main.mp4"), "video")
    assert float(video["duration"]) == pytest.approx(2.0, abs=0.15)


def test_preview_bg(project: Path) -> None:
    _invoke("preview-bg", "-C", str(project))
    assert _stream(_probe(project / "build/preview/bg.mp4"), "video")["codec_name"] == "h264"


def test_overlay_is_transparent_except_lyrics(project: Path) -> None:
    _invoke("overlay", "-C", str(project))

    output = project / "build/overlay.mov"
    video = _stream(_probe(output), "video")
    assert video["codec_name"] == "prores"
    assert video["pix_fmt"].startswith("yuva444p")
    assert _max_alpha(output, 1.0) > 200
    assert _max_alpha(output, 1.8) == 0


def test_release_numbers_videos(project: Path) -> None:
    _invoke("build", "-C", str(project))
    _invoke("release", "-C", str(project))
    assert (project / "release/test-v1.2.0.mp4").is_file()

    again = runner.invoke(app, ["release", "-C", str(project)])
    assert again.exit_code == 1
    assert "同じ内容が既にあります" in again.output

    # 見た目を変えて書き出し直すと、同じ音源のまま次の番号が付く
    # （テスト用のフォントは "A" しか持たないので、字を変えずに数を変える）
    lyrics = project / "src/lyrics.ass"
    lyrics.write_text(lyrics.read_text(encoding="utf-8").replace("AAAA", "A A"), encoding="utf-8")
    _invoke("build", "-C", str(project))
    _invoke("release", "-C", str(project))
    assert (project / "release/test-v1.2.1.mp4").is_file()


def test_release_compares_the_inputs_recorded_by_build(project: Path) -> None:
    _invoke("build", "-C", str(project))
    assert (project / "build/.work/main-inputs.json").is_file()
    later = (project / "build/main.mp4").stat().st_mtime + 10

    # 実際のフォントの記録を読み戻して比べられる（細かい場合分けは test_release.py）
    config = project / "utavideo.toml"
    config.write_text(config.read_text(encoding="utf-8") + '[description]\ntext = "概要"\n', encoding="utf-8")
    for path in (config, project / "src/lyrics.ass"):
        os.utime(path, (later, later))
    _invoke("release", "-C", str(project))


@pytest.mark.parametrize(
    ("reader", "attr", "rel", "name"),
    [
        (cli.subs, "load", "src/lyrics.ass", "lyrics.file"),
        (cli, "probe_audio", "src/mix/テスト v1.2.wav", "audio.file"),
    ],
)
def test_release_stops_when_an_input_changes_after_build_read_it(
    project: Path, monkeypatch: pytest.MonkeyPatch, reader: object, attr: str, rel: str, name: str
) -> None:
    # 読んだ後（フォント一覧の作成中など）に保存されると、動画は古い内容になる。記録も古い側でないと止まらない
    original = getattr(reader, attr)

    def read_then_save(path: Path):
        result = original(path)
        (project / rel).write_bytes((project / rel).read_bytes() + b"\n")
        return result

    monkeypatch.setattr(reader, attr, read_then_save)
    _invoke("build", "-C", str(project))

    result = runner.invoke(app, ["release", "-C", str(project)])
    assert result.exit_code == 1
    assert f"（{name}）" in result.output


def test_locked_output_keeps_partial(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.replace

    def replace(self: Path, target: Path) -> Path:
        if self.name == "bg.partial.mp4":  # 出力先を他のアプリが開いているときの drvfs の挙動
            raise PermissionError(13, "Permission denied")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    result = runner.invoke(app, ["preview-bg", "-C", str(project)])
    assert result.exit_code == 1
    assert "他のアプリ" in result.output
    assert (project / "build/preview/bg.partial.mp4").is_file()
