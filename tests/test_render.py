"""ffmpeg を実際に動かす結合テスト。"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import MakeFont, invoke, use_fake_ffmpeg
from utavideo import cli
from utavideo.cli import app
from utavideo.ffmpeg import subtitles_filter_error
from utavideo.project import scaffold

pytestmark = pytest.mark.skipif(subtitles_filter_error() is not None, reason="libass 付きの ffmpeg が必要")

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


def test_check_passes(project: Path) -> None:
    output = invoke("check", "-C", str(project)).output
    assert "問題ありません" in output
    assert "release 先" in output and "test-v1.2.0.mp4" in output  # 次に付く名前


def test_check_counts_warnings_instead_of_saying_ok(project: Path) -> None:
    # 音源は 2 秒。その終わりを跨ぐ行を足す
    lyrics = LYRICS.format(font="Test Sans") + "Dialogue: 0,0:00:01.80,0:00:03.00,Lyrics,,0,0,0,,BBBB\n"
    (project / "src/lyrics.ass").write_text(lyrics, encoding="utf-8")

    output = invoke("check", "-C", str(project)).output
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


def test_check_lists_the_other_results_when_ffmpeg_has_no_libass(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 書き出せないことは伝えつつ、1回の check で直すべきことが全部分かるように、エラーの一覧に並べる
    use_fake_ffmpeg(tmp_path, monkeypatch, reply="Unknown filter 'subtitles'.")

    result = runner.invoke(app, ["check", "-C", str(project)])

    assert result.exit_code == 1
    assert "libass" in result.output
    assert "曲名" in result.output and "歌詞" in result.output and "フォント" in result.output


def test_check_reports_missing_font(project: Path) -> None:
    (project / "src/lyrics.ass").write_text(LYRICS.format(font="Nope Sans"), encoding="utf-8")
    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "Nope Sans" in result.output


def test_build_writes_main_mp4(project: Path) -> None:
    invoke("build", "-C", str(project))

    output = project / "build/main.mp4"
    info = _probe(output)
    video, audio = _stream(info, "video"), _stream(info, "audio")
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 320, 180)
    assert video["color_space"] == "bt709"
    assert (audio["codec_name"], audio["sample_rate"]) == ("aac", "48000")
    assert float(info["format"]["duration"]) == pytest.approx(2.0, abs=0.15)
    assert not (project / "build/main.partial.mp4").exists()


def test_video_focus_moves_the_background(project: Path) -> None:
    frames = []
    for focus in ("[0, 0.5]", "[1, 0.5]"):
        config = TOML.format(background="bg.png").replace(
            "size = [320, 180]", f"size = [180, 180]\nfocus = {focus}"
        )
        (project / "utavideo.toml").write_text(config, encoding="utf-8")
        (project / "src/lyrics.ass").write_text(
            LYRICS.format(font="Test Sans").replace("PlayResX: 320", "PlayResX: 180"), encoding="utf-8"
        )
        invoke("build", "-C", str(project))
        frames.append(_pixels(project / "build/main.mp4"))
    assert frames[0] != frames[1]


def test_gif_background_loops_for_whole_audio(project: Path) -> None:
    (project / "utavideo.toml").write_text(TOML.format(background="loop.gif"), encoding="utf-8")
    invoke("build", "-C", str(project))
    video = _stream(_probe(project / "build/main.mp4"), "video")
    assert float(video["duration"]) == pytest.approx(2.0, abs=0.15)


def test_preview_bg(project: Path) -> None:
    invoke("preview-bg", "-C", str(project))
    assert _stream(_probe(project / "build/preview/bg.mp4"), "video")["codec_name"] == "h264"


def test_overlay_is_transparent_except_lyrics(project: Path) -> None:
    invoke("overlay", "-C", str(project))

    output = project / "build/overlay.mov"
    video = _stream(_probe(output), "video")
    assert video["codec_name"] == "prores"
    assert video["pix_fmt"].startswith("yuva444p")
    assert _max_alpha(output, 1.0) > 200
    assert _max_alpha(output, 1.8) == 0


def test_release_numbers_videos(project: Path) -> None:
    invoke("build", "-C", str(project))
    invoke("release", "-C", str(project))
    assert (project / "release/test-v1.2.0.mp4").is_file()

    again = runner.invoke(app, ["release", "-C", str(project)])
    assert again.exit_code == 1
    assert "同じ内容が既にあります" in again.output

    # 見た目を変えて書き出し直すと、同じ音源のまま次の番号が付く
    # （テスト用のフォントは "A" しか持たないので、字を変えずに数を変える）
    lyrics = project / "src/lyrics.ass"
    lyrics.write_text(lyrics.read_text(encoding="utf-8").replace("AAAA", "A A"), encoding="utf-8")
    invoke("build", "-C", str(project))
    invoke("release", "-C", str(project))
    assert (project / "release/test-v1.2.1.mp4").is_file()


def test_release_compares_the_inputs_recorded_by_build(project: Path) -> None:
    invoke("build", "-C", str(project))
    assert (project / "build/.work/main-inputs.json").is_file()
    later = (project / "build/main.mp4").stat().st_mtime + 10

    # 実際のフォントの記録を読み戻して比べられる（細かい場合分けは test_release.py）
    config = project / "utavideo.toml"
    config.write_text(config.read_text(encoding="utf-8") + '[description]\ntext = "概要"\n', encoding="utf-8")
    for path in (config, project / "src/lyrics.ass"):
        os.utime(path, (later, later))
    invoke("release", "-C", str(project))


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
    invoke("build", "-C", str(project))

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


THUMBNAIL = """
[[thumbnails]]
name = "main"
file = "src/thumbnail.ass"
{extra}
"""
THUMBNAIL_ASS = LYRICS.replace("PlayResX: 320\nPlayResY: 180", "PlayResX: 90\nPlayResY: 90").replace(
    "Dialogue: 0,0:00:00.20,0:00:01.50,Lyrics,,0,0,0,,AAAA",
    "Dialogue: 0,0:00:00.00,9:59:59.99,Lyrics,,0,0,0,,AA",
)


def _with_thumbnail(project: Path, background: str = "bg.png", extra: str = "size = [90, 90]") -> None:
    config = TOML.format(background=background) + THUMBNAIL.format(extra=extra)
    (project / "utavideo.toml").write_text(config, encoding="utf-8")
    (project / "src/thumbnail.ass").write_text(THUMBNAIL_ASS.format(font="Test Sans"), encoding="utf-8")


def _pixels(path: Path) -> bytes:
    out = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    return out.stdout


def test_thumbnail_draws_ass_over_background(project: Path) -> None:
    _with_thumbnail(project)
    bg = invoke("thumbnail", "-C", str(project), "--bg-only")
    assert "バイト" in bg.output
    result = invoke("thumbnail", "-C", str(project))
    assert "バイト" in result.output

    thumbnail, background = project / "build/thumbnail/main.png", project / "build/thumbnail/bg/main.png"
    for path in (thumbnail, background):
        video = _stream(_probe(path), "video")
        assert (video["codec_name"], video["width"], video["height"]) == ("png", 90, 90)
    assert _pixels(thumbnail) != _pixels(background)  # 文字が描かれている
    assert not (project / "build/thumbnail/main.partial.png").exists()


def test_thumbnail_background_only_does_not_need_the_ass(project: Path) -> None:
    _with_thumbnail(project)
    (project / "src/thumbnail.ass").unlink()
    invoke("thumbnail", "-C", str(project), "--bg-only")
    result = runner.invoke(app, ["thumbnail", "-C", str(project)])
    assert result.exit_code == 1
    assert "file のファイルがありません" in result.output


def test_thumbnail_uses_the_frame_at_the_given_time(project: Path) -> None:
    # 4 fps・0.5 秒の GIF。0.25 秒のフレームは 0 秒と違う絵
    _with_thumbnail(project, "loop.gif", 'size = [90, 90]\nat = "0:00.25"')
    invoke("thumbnail", "-C", str(project), "--bg-only")
    later = _pixels(project / "build/thumbnail/bg/main.png")
    _with_thumbnail(project, "loop.gif")
    invoke("thumbnail", "-C", str(project), "--bg-only")
    assert _pixels(project / "build/thumbnail/bg/main.png") != later


@pytest.mark.parametrize(
    ("background", "at", "message"),
    [
        ("bg.png", "at = 1", "画像"),
        ("loop.gif", 'at = "0:01"', "背景の長さ（0:00.500）以上"),
    ],
)
def test_thumbnail_rejects_unusable_time(project: Path, background: str, at: str, message: str) -> None:
    _with_thumbnail(project, background, f"size = [90, 90]\n{at}")
    for command in (["thumbnail", "--bg-only"], ["check"]):
        result = runner.invoke(app, [*command, "-C", str(project)])
        assert result.exit_code == 1
        assert message in result.output


def test_thumbnail_reports_when_ffmpeg_writes_nothing(project: Path) -> None:
    # 長さ 0.5 秒の GIF の最後のフレームは 0.25 秒。それより後には書き出すフレームが無い
    _with_thumbnail(project, "loop.gif", "size = [90, 90]\nat = 0.4")
    result = runner.invoke(app, ["thumbnail", "-C", str(project), "--bg-only"])
    assert result.exit_code == 1
    assert "何も書き出しませんでした" in result.output
    assert list((project / "build/thumbnail/bg").glob("*.png")) == []


def test_thumbnail_name_selection(project: Path) -> None:
    _with_thumbnail(project)
    result = runner.invoke(app, ["thumbnail", "-C", str(project), "--name", "square"])
    assert result.exit_code == 1
    assert "main" in result.output

    (project / "utavideo.toml").write_text(TOML.format(background="bg.png"), encoding="utf-8")
    empty = runner.invoke(app, ["thumbnail", "-C", str(project)])
    assert empty.exit_code == 1
    assert "[[thumbnails]]" in empty.output


def test_check_warns_about_thumbnail_lines_not_drawn(project: Path) -> None:
    _with_thumbnail(project)
    ass = project / "src/thumbnail.ass"
    ass.write_text(
        ass.read_text(encoding="utf-8").replace("0:00:00.00,9:59", "0:00:01.00,9:59"), encoding="utf-8"
    )
    output = invoke("check", "-C", str(project)).output
    assert "サムネイル main: 0 秒に表示されない行" in output


VERTICAL = """
[vertical]
size = [180, 320]
{extra}
"""


def _with_shorts(project: Path, shorts: str = '[[shorts]]\nname = "chorus"\n', extra: str = "") -> None:
    config = TOML.format(background="bg.png") + VERTICAL.format(extra=extra) + shorts
    (project / "utavideo.toml").write_text(config, encoding="utf-8")


def _add_vertical_lines(project: Path, *lines: str) -> None:
    vertical = project / "src/vertical.ass"
    vertical.write_text(
        vertical.read_text(encoding="utf-8") + "".join(f"{line}\n" for line in lines), encoding="utf-8"
    )


def test_check_inspects_the_vertical_ass_only_when_there_are_shorts(project: Path) -> None:
    _with_shorts(project, shorts="")
    invoke("vertical-ass", "-C", str(project))
    assert "縦用 .ass" not in invoke("check", "-C", str(project)).output

    _with_shorts(project)
    _add_vertical_lines(project, "Comment: 0,0:00:00.00,0:00:01.80,Short,,0,0,0,,chorus")
    output = invoke("check", "-C", str(project)).output
    assert "縦用 .ass: src/vertical.ass（180x320）" in output
    assert "ショート: chorus" in output
    assert "問題ありません" in output  # vertical-ass で写した歌詞は、本編と食い違わない

    lyrics = project / "src/lyrics.ass"
    lyrics.write_text(lyrics.read_text(encoding="utf-8").replace(",AAAA", ",AAAB"), encoding="utf-8")
    output = invoke("check", "-C", str(project)).output
    assert "本編との突き合わせ: 本編と文字が違います（0:00:00.200）: 本編「AAAB」" in output

    vertical = project / "src/vertical.ass"
    text = vertical.read_text(encoding="utf-8")
    vertical.write_text(
        text.replace("Test Sans", "Nope Sans").replace("PlayResY: 320", "PlayResY: 180"), encoding="utf-8"
    )
    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "縦用 .ass: PlayRes 180x180" in result.output
    assert "縦用 .ass: フォント 'Nope Sans'" in result.output
    # 縦用 .ass の誤りで、本編の書き出しは止めない
    invoke("build", "-C", str(project))


def test_check_reports_a_missing_vertical_ass_and_sections(project: Path) -> None:
    _with_shorts(project)
    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "utavideo vertical-ass で作れます" in result.output

    invoke("vertical-ass", "-C", str(project))
    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "ショート chorus: 区間の行" in result.output

    # 音源は 2 秒。歌詞の行は 0.2〜1.5 秒
    _add_vertical_lines(project, "Comment: 0,0:00:01.00,0:00:02.50,Short,,0,0,0,,chorus")
    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "音源の長さ（0:00:02.000）を超えています" in result.output
    invoke("build", "-C", str(project))


def test_check_warns_only_about_lines_in_sections(project: Path) -> None:
    _with_shorts(project)
    invoke("vertical-ass", "-C", str(project))
    long_line = "A" * 20
    _add_vertical_lines(
        project,
        "Comment: 0,0:00:01.00,0:00:02.00,Short,,0,0,0,,chorus",
        "Comment: 0,0:00:00.00,0:00:01.00,Short,,0,0,0,,unused",
        # 区間の外の行ははみ出しても警告しない
        f"Dialogue: 0,0:00:00.00,0:00:00.10,Lyrics,,0,0,0,,{long_line}",
        f"Dialogue: 0,0:00:01.60,0:00:01.90,Lyrics,,0,0,0,,{long_line}",
    )
    output = invoke("check", "-C", str(project)).output
    assert output.count("はみ出しそう") == 1
    assert "0:00:01.600「AAAA" in output
    assert "区間の頭（0:00:01.000）が歌詞の行の途中にかかっています" in output
    assert "どの [[shorts]] の name にも合わない区間の行があります" in output
    assert "本編との突き合わせ: 本編に時刻の重なる行がありません" in output


def test_preview_bg_vertical_uses_the_vertical_size_and_focus(project: Path) -> None:
    _with_shorts(project, shorts="")
    result = runner.invoke(app, ["preview-bg", "--vertical", "-C", str(project)])
    assert result.exit_code == 1
    assert "utavideo vertical-ass で作れます" in result.output

    invoke("vertical-ass", "-C", str(project))
    frames = []
    for focus in ("[0, 0.5]", "[1, 0.5]"):
        _with_shorts(project, shorts="", extra=f"focus = {focus}")
        invoke("preview-bg", "--vertical", "-C", str(project))
        output = project / "build/preview/vertical-bg.mp4"
        info = _probe(output)
        video = _stream(info, "video")
        assert (video["codec_name"], video["width"], video["height"]) == ("h264", 180, 320)
        assert _stream(info, "audio")["codec_name"] == "aac"
        frames.append(_pixels(output))
    assert frames[0] != frames[1]
    assert (project / "build/.work/vertical-preview.ass").is_file()
    assert not (project / "build/preview/bg.mp4").exists()


def test_layout_res_that_squashes_the_lyrics_stops_the_build(project: Path) -> None:
    lyrics = project / "src/lyrics.ass"
    text = lyrics.read_text(encoding="utf-8").replace(
        "PlayResY: 180", "PlayResY: 180\nLayoutResX: 180\nLayoutResY: 320"
    )
    lyrics.write_text(text, encoding="utf-8")
    result = runner.invoke(app, ["build", "-C", str(project)])
    assert result.exit_code == 1
    assert "LayoutResX / LayoutResY 180x320" in result.output
