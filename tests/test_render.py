"""ffmpeg を実際に動かす結合テスト。"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import MakeFont, invoke, use_fake_ffmpeg
from utavideo import analyze, cli, graph, score
from utavideo.cli import app
from utavideo.ffmpeg import (
    LoudnormMeasurement,
    LoudnormTarget,
    measure_loudness,
    rubberband_filter_error,
    subtitles_filter_error,
)
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
[inst]
audio = "src/mix/inst.wav"
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


def _mean_volume_db(path: Path, *, band: tuple[int, int]) -> float:
    """band（Hz）に絞ったときの平均音量。周波数の違う2つの音源を聞き分けるのに使う。"""
    low, high = band
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path),
         "-af", f"highpass=f={low},lowpass=f={high},volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    match = re.search(r"mean_volume: (-?[\d.]+) dB", out.stderr)
    assert match is not None, out.stderr
    return float(match[1])


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
    # inst 用の音源は本編と別ファイル（issue #106）。周波数を変えて聞き分けられるようにする
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=2", str(root / "src/mix/inst.wav"))
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


def test_check_reports_a_missing_layer_file(project: Path) -> None:
    toml = (project / "utavideo.toml").read_text(encoding="utf-8")
    toml += '\n[[layers]]\nname = "logo"\nfile = "src/layers/logo.png"\n'
    (project / "utavideo.toml").write_text(toml, encoding="utf-8")

    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "[[layers]] logo: file のファイルがありません" in result.output


def test_check_reports_an_unsupported_layer_format(project: Path) -> None:
    (project / "src/layers").mkdir(parents=True, exist_ok=True)
    (project / "src/layers/logo.txt").write_text("not a video", encoding="utf-8")
    toml = (project / "utavideo.toml").read_text(encoding="utf-8")
    toml += '\n[[layers]]\nname = "logo"\nfile = "src/layers/logo.txt"\n'
    (project / "utavideo.toml").write_text(toml, encoding="utf-8")

    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "[[layers]] logo: file の形式に対応していません: .txt" in result.output


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


def _make_logo(path: Path, size: tuple[int, int], color: str) -> None:
    """[[layers]] 用の、不透明な単色 PNG を合成する。"""
    w, h = size
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d=1", "-frames:v", "1", str(path)
    )  # fmt: skip


def _pixels_at(path: Path, at: float) -> bytes:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
        check=True,
    )  # fmt: skip
    return out.stdout


LAYER_ASS = LYRICS.format(font="Test Sans") + (
    # 全画面を塗りつぶす不透明な行（ASS の色は &HBBGGRR& なので、これは青）。
    # layer との前後関係を見るのに使う。0 秒ちょうどは subtitles フィルタの立ち上がりで
    # 描かれないことがあるので、少し後ろから始める
    "Dialogue: 0,0:00:00.10,0:00:02.00,Lyrics,,0,0,0,,"
    r"{\an7\pos(0,0)\c&HFF0000&\bord0\shad0\p1}m 0 0 l 320 0 320 180 0 180{\p0}"
)


def _with_layer(project: Path, layer_toml: str) -> None:
    (project / "src/layers").mkdir(parents=True, exist_ok=True)
    _make_logo(project / "src/layers/logo.png", (40, 20), "0x00FF00")
    config = TOML.format(background="bg.png") + f'\n[[layers]]\nname = "logo"\n{layer_toml}'
    (project / "utavideo.toml").write_text(config, encoding="utf-8")


def test_layer_is_composited_over_the_background(project: Path) -> None:
    invoke("build", "-C", str(project))
    without_layer = _pixels(project / "build/main.mp4")

    _with_layer(project, 'file = "src/layers/logo.png"\n')
    invoke("build", "-C", str(project))
    with_layer = _pixels(project / "build/main.mp4")

    assert without_layer != with_layer


def test_layer_appears_only_within_its_time_range(project: Path) -> None:
    # crf=0（可逆）で書き出し、フレームの md5 で「その区間のフレームだけ違う」ことを確かめる
    config = TOML.format(background="bg.png").replace("fps = 10", "fps = 10\ncrf = 0")
    (project / "utavideo.toml").write_text(config, encoding="utf-8")
    invoke("build", "-C", str(project))
    baseline = _frame_md5(project / "build/main.mp4")

    (project / "src/layers").mkdir(parents=True, exist_ok=True)
    _make_logo(project / "src/layers/logo.png", (40, 20), "0x00FF00")
    layered = config + (
        '\n[[layers]]\nname = "logo"\nfile = "src/layers/logo.png"\n'
        'start = "0:00.5"\nend = "0:00.95"\nanchor = "top-left"\nmargin = [0, 0]\n'
    )
    (project / "utavideo.toml").write_text(layered, encoding="utf-8")
    invoke("build", "-C", str(project))
    with_layer = _frame_md5(project / "build/main.mp4")

    assert len(baseline) == len(with_layer) == 20  # 10fps ✕ 2 秒
    for i, (base, layer) in enumerate(zip(baseline, with_layer, strict=True)):
        if 5 <= i < 10:  # 0.5〜0.9 秒（0.95 秒は含めない境界にした）
            assert base != layer, i
        else:
            assert base == layer, i


def test_negative_layer_is_covered_by_lyrics_but_positive_layer_covers_them(project: Path) -> None:
    (project / "src/lyrics.ass").write_text(LAYER_ASS, encoding="utf-8")
    (project / "src/layers").mkdir(parents=True, exist_ok=True)
    _make_logo(project / "src/layers/logo.png", (320, 180), "0x00FF00")

    behind = TOML.format(background="bg.png") + (
        '\n[[layers]]\nname = "logo"\nfile = "src/layers/logo.png"\nlayer = -1\n'
    )
    (project / "utavideo.toml").write_text(behind, encoding="utf-8")
    invoke("build", "-C", str(project))
    behind_pixels = _pixels_at(project / "build/main.mp4", 1.0)

    front = TOML.format(background="bg.png") + (
        '\n[[layers]]\nname = "logo"\nfile = "src/layers/logo.png"\nlayer = 1\n'
    )
    (project / "utavideo.toml").write_text(front, encoding="utf-8")
    invoke("build", "-C", str(project))
    front_pixels = _pixels_at(project / "build/main.mp4", 1.0)

    # 全画面緑のレイヤーが、layer < 0 では青い歌詞に隠れ、layer >= 0 では歌詞の上に出る
    assert behind_pixels != front_pixels


def _make_avatar_raw(path: Path, size: tuple[int, int] = (320, 180), duration: float = 1.0) -> None:
    """[avatar] の見本。ブルーバック（キーで抜ける）の上に、白い箱（被写体の代わり）を置く。"""
    w, h = size
    box = max(2, round(w / 4))
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        "-f", "lavfi", "-i", f"color=c=0x0000ff:s={w}x{h}:d={duration}",
        "-f", "lavfi", "-i", f"color=c=0xffffff:s={box}x{box}:d={duration}",
        "-filter_complex", "[0:v][1:v]overlay=(W-w)/2:(H-h)/2[v]",
        "-map", "[v]",
        str(path),
    )  # fmt: skip


def _with_avatar(project: Path, avatar_toml: str) -> None:
    config = TOML.format(background="bg.png") + f"\n[avatar]\n{avatar_toml}"
    (project / "utavideo.toml").write_text(config, encoding="utf-8")


def test_check_reports_a_missing_avatar_file(project: Path) -> None:
    toml = (project / "utavideo.toml").read_text(encoding="utf-8")
    toml += '\n[avatar]\nfile = "src/avatar/avatar-raw.mp4"\n'
    (project / "utavideo.toml").write_text(toml, encoding="utf-8")

    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "[avatar] file のファイルがありません" in result.output


def test_check_reports_an_unsupported_avatar_format(project: Path) -> None:
    (project / "src/avatar").mkdir(parents=True, exist_ok=True)
    (project / "src/avatar/avatar-raw.txt").write_text("not a video", encoding="utf-8")
    toml = (project / "utavideo.toml").read_text(encoding="utf-8")
    toml += '\n[avatar]\nfile = "src/avatar/avatar-raw.txt"\n'
    (project / "utavideo.toml").write_text(toml, encoding="utf-8")

    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "[avatar] file の形式に対応していません: .txt" in result.output


def test_avatar_is_composited_over_the_background_after_chroma_key(project: Path) -> None:
    invoke("build", "-C", str(project))
    without_avatar = _pixels(project / "build/main.mp4")

    _make_avatar_raw(project / "src/avatar/avatar-raw.mp4")
    _with_avatar(project, 'file = "src/avatar/avatar-raw.mp4"\nsync = 0\n')
    invoke("build", "-C", str(project))
    with_avatar = _pixels(project / "build/main.mp4")

    assert without_avatar != with_avatar


def test_avatar_prepared_video_is_reused_until_key_settings_change(project: Path) -> None:
    _make_avatar_raw(project / "src/avatar/avatar-raw.mp4")
    _with_avatar(project, 'file = "src/avatar/avatar-raw.mp4"\nsync = 0\n')

    invoke("build", "-C", str(project))
    prepared = project / "build/.work/avatar-prepared.mov"
    assert prepared.is_file()
    stamp = prepared.stat().st_mtime_ns

    invoke("build", "-C", str(project))
    assert prepared.stat().st_mtime_ns == stamp  # 変わっていなければ作り直さない

    _with_avatar(project, 'file = "src/avatar/avatar-raw.mp4"\nsync = 0\nsimilarity = 0.5\n')
    invoke("build", "-C", str(project))
    assert prepared.stat().st_mtime_ns != stamp  # key 系の設定が変われば作り直す

    # scale・anchor・margin・layer（気分で変えたいもの）を変えても中間動画は作り直さない
    stamp = prepared.stat().st_mtime_ns
    _with_avatar(
        project, 'file = "src/avatar/avatar-raw.mp4"\nsync = 0\nsimilarity = 0.5\nscale = 2.0\nlayer = 50\n'
    )
    invoke("build", "-C", str(project))
    assert prepared.stat().st_mtime_ns == stamp


def test_preview_bg(project: Path) -> None:
    invoke("preview-bg", "-C", str(project))
    assert _stream(_probe(project / "build/preview/bg.mp4"), "video")["codec_name"] == "h264"


def test_preview_writes_a_still_image_for_the_given_time(project: Path) -> None:
    result = invoke("preview", "-C", str(project), "--at", "0.2")

    output = project / "build/.work/preview.png"
    assert str(output) in result.output
    stream = _stream(_probe(output), "video")
    assert stream["codec_name"] == "png"
    assert (int(stream["width"]), int(stream["height"])) == (320, 180)


def test_preview_writes_a_short_video_for_the_given_duration(project: Path) -> None:
    result = invoke("preview", "-C", str(project), "--at", "0.2", "--duration", "1")

    output = project / "build/.work/preview.mp4"
    assert str(output) in result.output
    info = _probe(output)
    assert _stream(info, "video")["codec_name"] == "h264"
    assert float(info["format"]["duration"]) == pytest.approx(1.0, abs=0.2)


def test_preview_still_wraps_at_for_a_looping_background(project: Path) -> None:
    # loop.gif は 0.5 秒。素材の実長を超える --at でも、build と同じくループして書き出せる（issue #131）。
    # 1.7 % 0.5 == 0.2 なので、中身も --at 0.2 と同じフレームになるはず
    (project / "utavideo.toml").write_text(TOML.format(background="loop.gif"), encoding="utf-8")
    output = project / "build/.work/preview.png"

    invoke("preview", "-C", str(project), "--at", "0.2")
    pixels_at_0_2 = _pixels(output)

    result = invoke("preview", "-C", str(project), "--at", "1.7")
    assert str(output) in result.output
    assert _stream(_probe(output), "video")["codec_name"] == "png"
    assert _pixels(output) == pixels_at_0_2


def test_preview_rejects_a_duration_shorter_than_one_frame(project: Path) -> None:
    result = runner.invoke(app, ["preview", "-C", str(project), "--duration", "0.02"])
    assert result.exit_code == 1
    assert "--duration" in result.output


def test_preview_rejects_a_badly_formatted_at(project: Path) -> None:
    result = runner.invoke(app, ["preview", "-C", str(project), "--at", "not-a-time"])
    assert result.exit_code == 1
    assert "--at" in result.output


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
        (analyze.subs, "load", "src/lyrics.ass", "lyrics.file"),
        (analyze, "probe_audio", "src/mix/テスト v1.2.wav", "audio.file"),
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
    bg = invoke("preview-bg", "-C", str(project), "--target", "thumbnail")
    assert "バイト" in bg.output
    result = invoke("thumbnail", "-C", str(project))
    assert "バイト" in result.output

    thumbnail, background = project / "build/thumbnail/main.png", project / "build/thumbnail/bg/main.png"
    for path in (thumbnail, background):
        video = _stream(_probe(path), "video")
        assert (video["codec_name"], video["width"], video["height"]) == ("png", 90, 90)
    assert _pixels(thumbnail) != _pixels(background)  # 文字が描かれている
    assert not (project / "build/thumbnail/main.partial.png").exists()


def test_thumbnail_records_inputs_only_when_not_bg_only(project: Path) -> None:
    _with_thumbnail(project)
    record = project / "build/.work/thumbnail-main-inputs.json"

    invoke("preview-bg", "-C", str(project), "--target", "thumbnail")
    assert not record.exists()

    invoke("thumbnail", "-C", str(project))
    assert record.is_file()
    assert "サムネイル" not in invoke("status", "-C", str(project)).output


def test_thumbnail_background_only_does_not_need_the_ass(project: Path) -> None:
    _with_thumbnail(project)
    (project / "src/thumbnail.ass").unlink()
    invoke("preview-bg", "-C", str(project), "--target", "thumbnail")
    result = runner.invoke(app, ["thumbnail", "-C", str(project)])
    assert result.exit_code == 1
    assert "file のファイルがありません" in result.output


def test_thumbnail_reports_a_missing_layer_file(project: Path) -> None:
    """サムネイルも [[layers]] を重ねるので、preview-bg --target thumbnail・thumbnail の両方で検査する。"""
    _with_thumbnail(project)
    toml = (project / "utavideo.toml").read_text(encoding="utf-8")
    toml += '\n[[layers]]\nname = "logo"\nfile = "src/layers/logo.png"\n'
    (project / "utavideo.toml").write_text(toml, encoding="utf-8")

    bg_result = runner.invoke(app, ["preview-bg", "-C", str(project), "--target", "thumbnail"])
    assert bg_result.exit_code == 1
    assert "[[layers]] logo: file のファイルがありません" in bg_result.output

    result = runner.invoke(app, ["thumbnail", "-C", str(project)])
    assert result.exit_code == 1
    assert "[[layers]] logo: file のファイルがありません" in result.output


def test_thumbnail_uses_the_frame_at_the_given_time(project: Path) -> None:
    # 4 fps・0.5 秒の GIF。0.25 秒のフレームは 0 秒と違う絵
    _with_thumbnail(project, "loop.gif", 'size = [90, 90]\nat = "0:00.25"')
    invoke("preview-bg", "-C", str(project), "--target", "thumbnail:main")
    later = _pixels(project / "build/thumbnail/bg/main.png")
    _with_thumbnail(project, "loop.gif")
    invoke("preview-bg", "-C", str(project), "--target", "thumbnail:main")
    assert _pixels(project / "build/thumbnail/bg/main.png") != later


def test_thumbnail_includes_only_layers_active_at_the_given_time(project: Path) -> None:
    """サムネイルの `at`（無ければ 0 秒）が [[layers]] の start・end に入るものだけ重ねる。"""
    (project / "src/layers").mkdir(parents=True, exist_ok=True)
    _make_logo(project / "src/layers/logo.png", (90, 90), "0x00FF00")
    config = TOML.format(background="bg.png") + THUMBNAIL.format(extra="size = [90, 90]")
    (project / "src/thumbnail.ass").write_text(THUMBNAIL_ASS.format(font="Test Sans"), encoding="utf-8")

    def _build(layer_toml: str) -> bytes:
        (project / "utavideo.toml").write_text(config + layer_toml, encoding="utf-8")
        invoke("thumbnail", "-C", str(project))
        return _pixels(project / "build/thumbnail/main.png")

    # サムネイルは既定で 0 秒を描く。start が 0 秒より後のレイヤーは重ねない
    outside = _build('[[layers]]\nname = "logo"\nfile = "src/layers/logo.png"\nstart = "0:00.10"\n')
    # 区間の無いレイヤーは常に表示する
    inside = _build('[[layers]]\nname = "logo"\nfile = "src/layers/logo.png"\n')
    assert inside != outside


@pytest.mark.parametrize(
    ("background", "at", "message"),
    [
        ("bg.png", "at = 1", "画像"),
        ("loop.gif", 'at = "0:01"', "背景の長さ（0:00.500）以上"),
    ],
)
def test_thumbnail_rejects_unusable_time(project: Path, background: str, at: str, message: str) -> None:
    _with_thumbnail(project, background, f"size = [90, 90]\n{at}")
    for command in (["preview-bg", "--target", "thumbnail"], ["check"]):
        result = runner.invoke(app, [*command, "-C", str(project)])
        assert result.exit_code == 1
        assert message in result.output


def test_thumbnail_reports_when_ffmpeg_writes_nothing(project: Path) -> None:
    # 長さ 0.5 秒の GIF の最後のフレームは 0.25 秒。それより後には書き出すフレームが無い
    _with_thumbnail(project, "loop.gif", "size = [90, 90]\nat = 0.4")
    result = runner.invoke(app, ["preview-bg", "-C", str(project), "--target", "thumbnail"])
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
audio_fade_ms = [100, 200]  # 音源が 2 秒なので、既定値（300, 1000）では区間に収まらない
{extra}
"""


def _with_shorts(
    project: Path,
    shorts: str = '[[shorts]]\nname = "chorus"\n',
    extra: str = "",
    background: str = "bg.png",
) -> None:
    config = TOML.format(background=background) + VERTICAL.format(extra=extra) + shorts
    (project / "utavideo.toml").write_text(config, encoding="utf-8")


def _add_vertical_lines(project: Path, *lines: str) -> None:
    vertical = project / "src/vertical.ass"
    vertical.write_text(
        vertical.read_text(encoding="utf-8") + "".join(f"{line}\n" for line in lines), encoding="utf-8"
    )


def test_check_inspects_the_vertical_ass_only_when_there_are_shorts(project: Path) -> None:
    _with_shorts(project, shorts="")
    invoke("preview-bg", "-C", str(project))
    assert "縦用 .ass" not in invoke("check", "-C", str(project)).output

    _with_shorts(project)
    _add_vertical_lines(project, "Comment: 0,0:00:00.00,0:00:01.80,Short,,0,0,0,,chorus")
    output = invoke("check", "-C", str(project)).output
    assert "縦用 .ass: src/vertical.ass（180x320）" in output
    assert "ショート: chorus" in output
    assert "問題ありません" in output

    config = project / "utavideo.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("enabled = false", "enabled = true"), encoding="utf-8"
    )
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
    assert "utavideo preview-bg で作れます" in result.output

    invoke("preview-bg", "-C", str(project))
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
    """縦用 .ass の行（帯の文字）の警告は、区間の中の行だけ出す。"""
    _with_shorts(project)
    invoke("preview-bg", "-C", str(project))
    long_line = "A" * 20
    _add_vertical_lines(
        project,
        "Comment: 0,0:00:01.00,0:00:02.00,Short,,0,0,0,,chorus",
        "Comment: 0,0:00:00.00,0:00:01.00,Short,,0,0,0,,unused",
        # 区間の外の行ははみ出しても警告しない
        f"Dialogue: 0,0:00:00.00,0:00:00.10,VerticalBand,,0,0,0,,{long_line}",
        f"Dialogue: 0,0:00:01.60,0:00:01.90,VerticalBand,,0,0,0,,{long_line}",
    )
    output = invoke("check", "-C", str(project)).output
    assert output.count("はみ出しそう") == 1
    assert "0:00:01.600「AAAA" in output
    assert "どの [[shorts]] の name にも合わない区間の行があります" in output


def test_preview_bg_creates_the_vertical_ass_and_writes_both_previews(project: Path) -> None:
    """[vertical] があれば、vertical.lyrics が無くても preview-bg が自動で作り、両方の下敷きを書き出す。"""
    _with_shorts(project, shorts="")
    invoke("preview-bg", "-C", str(project))
    assert (project / "src/vertical.ass").is_file()
    assert (project / "build/preview/bg.mp4").is_file()  # 縦だけでなく本編の下敷きも作る

    frames = []
    for focus in ("[0, 0.5]", "[1, 0.5]"):
        _with_shorts(project, shorts="", extra=f"focus = {focus}")
        invoke("preview-bg", "-C", str(project))
        output = project / "build/preview/vertical-bg.mp4"
        info = _probe(output)
        video = _stream(info, "video")
        assert (video["codec_name"], video["width"], video["height"]) == ("h264", 180, 320)
        assert _stream(info, "audio")["codec_name"] == "aac"
        frames.append(_pixels(output))
    assert frames[0] != frames[1]
    assert (project / "build/.work/vertical-preview.ass").is_file()


def test_preview_bg_keeps_edits_to_an_existing_vertical_ass(project: Path) -> None:
    _with_shorts(project, shorts="")
    invoke("preview-bg", "-C", str(project))
    vertical = project / "src/vertical.ass"
    text = vertical.read_text(encoding="utf-8")
    assert "PlayResX: 180" in text
    assert "Video File: ../build/preview/vertical-bg.mp4" in text

    # 利用者が直した縦用 .ass を、次の preview-bg で上書きしない
    edited = text + "Dialogue: 0,0:00:00.00,0:00:01.00,VerticalBand,,0,0,0,,編集済み\n"
    vertical.write_text(edited, encoding="utf-8")
    invoke("preview-bg", "-C", str(project))
    assert vertical.read_text(encoding="utf-8") == edited


def test_preview_bg_rebases_the_vertical_bg_path_for_a_vertical_ass_in_another_folder(
    project: Path,
) -> None:
    """vertical.lyrics が本編の .ass と違うフォルダにあっても、下敷きへの相対パスを合わせる。"""
    _with_shorts(project, shorts="", extra='lyrics = "src/shorts/vertical.ass"')
    invoke("preview-bg", "-C", str(project))
    text = (project / "src/shorts/vertical.ass").read_text(encoding="utf-8")
    assert "Video File: ../../build/preview/vertical-bg.mp4" in text


def test_preview_bg_needs_the_lyrics_before_creating_the_vertical_ass(project: Path) -> None:
    """本編の歌詞が無ければ preview-bg 全体が止まり、縦用 .ass は作られない。"""
    _with_shorts(project, shorts="")
    (project / "src/lyrics.ass").unlink()
    result = runner.invoke(app, ["preview-bg", "-C", str(project)])
    assert result.exit_code == 1
    assert "lyrics.file" in result.output
    assert not (project / "src/vertical.ass").exists()


def test_preview_bg_for_blur_creates_a_vertical_ass_without_lyrics(project: Path) -> None:
    _with_shorts(project, shorts="")
    output = invoke("preview-bg", "-C", str(project)).output
    assert "曲名表示は自動で帯に入る" in output
    text = (project / "src/vertical.ass").read_text(encoding="utf-8")
    # 歌詞は本編の映像に入るので写さない。スタイルは Aegisub で選べるように写す
    assert "Dialogue:" not in text
    assert "Style: VerticalBand," in text


def test_layout_res_that_squashes_the_lyrics_stops_the_build(project: Path) -> None:
    lyrics = project / "src/lyrics.ass"
    text = lyrics.read_text(encoding="utf-8").replace(
        "PlayResY: 180", "PlayResY: 180\nLayoutResX: 180\nLayoutResY: 320"
    )
    lyrics.write_text(text, encoding="utf-8")
    result = runner.invoke(app, ["build", "-C", str(project)])
    assert result.exit_code == 1
    assert "LayoutResX / LayoutResY 180x320" in result.output


def _frame_md5(path: Path) -> list[str]:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v", "-f", "framemd5", "-c:v", "rawvideo", "-"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return [line.split(",")[-1].strip() for line in out.splitlines() if not line.startswith("#")]


def _mean_volume(path: Path, start: float, end: float) -> float:
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", str(start), "-to", str(end), "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        check=True,
        text=True,
    ).stderr  # fmt: skip
    found = re.search(r"mean_volume: (-?[\d.]+) dB", out)
    assert found is not None, out
    return float(found[1])


def _with_section(
    project: Path,
    *,
    shorts: str,
    line: str = "Comment: 0,0:00:00.53,0:00:01.77,Short,,0,0,0,,chorus",
    extra: str = "",
    background: str = "bg.png",
) -> None:
    _with_shorts(project, shorts=shorts, extra=extra, background=background)
    invoke("preview-bg", "-C", str(project))
    _add_vertical_lines(project, line)


def test_shorts_writes_the_section_and_the_wide_version_matches_main(project: Path) -> None:
    # 背景は 0.5 秒で一周する loop.gif。入力側で -ss せずに切ることを確かめるため、
    # 区間（0.53〜1.77 秒）が背景の2周目・3周目・4周目にまたがるようにする
    _with_section(project, shorts='[[shorts]]\nname = "chorus"\nwide = true\n', background="loop.gif")
    # 可逆で書き出して、本編と同じコマかをフレームの md5 で比べる
    config = project / "utavideo.toml"
    config.write_text(config.read_text(encoding="utf-8").replace("fps = 10", "fps = 10\ncrf = 0"), "utf-8")
    invoke("build", "-C", str(project))
    invoke("shorts", "-C", str(project))

    vertical_mp4 = project / "build/shorts/chorus.mp4"
    wide_mp4 = project / "build/shorts/wide/chorus.mp4"
    assert _stream(_probe(vertical_mp4), "video")["width"] == 180
    wide_info = _probe(wide_mp4)
    assert (_stream(wide_info, "video")["width"], _stream(wide_info, "video")["height"]) == (320, 180)
    # 区間は 0.53〜1.77 秒。10fps では 5〜18 フレーム目
    assert float(wide_info["format"]["duration"]) == pytest.approx(1.3, abs=0.05)
    main = _frame_md5(project / "build/main.mp4")
    wide = _frame_md5(wide_mp4)
    assert len(wide) == 13
    assert main[5:18] == wide
    assert main[4:17] != wide  # 1 フレームずれていない
    assert (project / "build/.work/shorts/chorus.ass").is_file()
    assert (project / "build/.work/shorts/wide/chorus.ass").is_file()


def test_shorts_records_inputs_and_status_shows_it_as_clean(project: Path) -> None:
    _with_section(project, shorts='[[shorts]]\nname = "chorus"\n')
    invoke("shorts", "-C", str(project))

    assert (project / "build/.work/shorts-chorus-inputs.json").is_file()
    # 出力自体は最新（"ショート chorus:" の行が無い）。release していないことは別の行で示すので、
    # ここでは見ない（issue #122）
    assert "ショート chorus:" not in invoke("status", "-C", str(project)).output


def test_shorts_composites_layers_on_both_the_vertical_and_wide_versions(project: Path) -> None:
    """blur（縦）は本編と同じ画面（frame）に、wide は本編と同じ画面にそのまま [[layers]] を重ねる。"""
    _with_section(project, shorts='[[shorts]]\nname = "chorus"\nwide = true\n')
    invoke("shorts", "-C", str(project))
    vertical_without = _pixels(project / "build/shorts/chorus.mp4")
    wide_without = _pixels(project / "build/shorts/wide/chorus.mp4")

    (project / "src/layers").mkdir(parents=True, exist_ok=True)
    _make_logo(project / "src/layers/logo.png", (40, 20), "0x00FF00")
    toml = (project / "utavideo.toml").read_text(encoding="utf-8")
    toml += '\n[[layers]]\nname = "logo"\nfile = "src/layers/logo.png"\n'
    (project / "utavideo.toml").write_text(toml, encoding="utf-8")
    invoke("shorts", "-C", str(project))
    vertical_with = _pixels(project / "build/shorts/chorus.mp4")
    wide_with = _pixels(project / "build/shorts/wide/chorus.mp4")

    assert vertical_with != vertical_without
    assert wide_with != wide_without


def test_shorts_fades_the_audio_at_both_edges(project: Path) -> None:
    _with_section(project, shorts='[[shorts]]\nname = "chorus"\n')
    invoke("shorts", "-C", str(project))
    output = project / "build/shorts/chorus.mp4"
    # フェードは [100, 200] ミリ秒。フェードインの窓（フェード期間 100ms の前半）は、
    # afade のランプ形状が ffmpeg のバージョンで微妙に変わり、10dB 差ちょうどでは
    # ffmpeg 9.0.2 で数 dB 足りず落ちることがある（実測 8.7dB。issue #49）ので、
    # 実測に余裕を持たせた 7dB を境目にする
    middle = _mean_volume(output, 0.5, 0.8)
    assert _mean_volume(output, 0, 0.05) < middle - 7
    assert _mean_volume(output, 1.25, 1.3) < middle - 10


def test_shorts_needs_a_name_that_exists(project: Path) -> None:
    _with_shorts(project, shorts="")
    result = runner.invoke(app, ["shorts", "-C", str(project)])
    assert result.exit_code == 1
    assert "[[shorts]] がありません" in result.output

    _with_section(project, shorts='[[shorts]]\nname = "chorus"\n[[shorts]]\nname = "intro"\n')
    result = runner.invoke(app, ["shorts", "-C", str(project), "--name", "nope"])
    assert result.exit_code == 1
    assert "あるのは chorus, intro" in result.output

    # --name を渡すと、区間の行の無いもう1本（intro）のエラーでは止まらない
    invoke("shorts", "-C", str(project), "--name", "chorus")
    assert (project / "build/shorts/chorus.mp4").is_file()
    assert not (project / "build/shorts/intro.mp4").exists()


# 本編の画面いっぱいに不透明な緑を描く行。帯に本編が写っていないかを、この色で見る
GREEN_SCREEN = (
    "Dialogue: 1,0:00:00.00,0:00:02.00,Lyrics,,0,0,0,,"
    r"{\an7\pos(0,0)\c&H00FF00&\bord0\shad0\p1}m 0 0 l 320 0 320 180 0 180{\p0}"
)
# 本編（320x180）を縦の幅（180）に縮めた高さ（偶数に丸めて 102）。実際の画素と突き合わせる
FRAME_HEIGHT = graph.frame_height((320, 180), 180)


def _greens_per_row(path: Path, size: tuple[int, int]) -> list[int]:
    """1フレーム目の、行ごとの緑（本編の映像に描いた色）の画素の数。

    純粋な緑 (0,255,0) は out_range=tv（BT.709 の legal レンジ）を経由するので厳密には
    戻らず、量子化・圧縮の丸め方が ffmpeg・x264 のバージョンで変わりうる（実測で G が 233
    に留まることがある。issue #50）。しきい値は 240 ではなく 200 にして揺れを吸収する。
    """
    width, height = size
    raw = _pixels(path)
    counts = []
    for y in range(height):
        row = raw[y * width * 3 : (y + 1) * width * 3]
        green = (row[x] < 16 and row[x + 1] > 200 and row[x + 2] < 16 for x in range(0, width * 3, 3))
        counts.append(sum(green))
    return counts


def test_shorts_blur_places_the_main_video_at_the_center_and_keeps_it_out_of_the_bands(
    project: Path,
) -> None:
    lyrics = project / "src/lyrics.ass"
    lyrics.write_text(lyrics.read_text(encoding="utf-8") + GREEN_SCREEN + "\n", encoding="utf-8")
    # 帯に緑が無いことを見るので、背景は緑を含まない1色にする（testsrc には緑の帯がある）
    _ffmpeg(
        "-f", "lavfi", "-i", "color=c=gray:size=640x360", "-frames:v", "1", str(project / "src/bg/bg.png")
    )
    _with_section(project, shorts='[[shorts]]\nname = "chorus"\n')
    invoke("shorts", "-C", str(project))
    output = project / "build/shorts/chorus.mp4"
    video = _stream(_probe(output), "video")
    assert (video["width"], video["height"]) == (180, 320)
    assert (project / "build/.work/shorts/frame/chorus.ass").is_file()

    # 本編は常に上下中央に置く。上下の帯には本編の緑が1画素も写らない（背景だけをぼかす）
    band = (320 - FRAME_HEIGHT) // 2
    counts = _greens_per_row(output, (180, 320))
    assert sum(counts[:band]) == 0
    assert sum(counts[band + FRAME_HEIGHT :]) == 0
    # 本編と帯の境目の数行は、縮小で混ざるので全部は緑にならない
    assert sum(1 for n in counts[band : band + FRAME_HEIGHT] if n == 180) > FRAME_HEIGHT - 5


def test_shorts_blur_draws_only_the_vertical_lines_and_puts_the_title_in_the_band(
    project: Path,
) -> None:
    _with_section(project, shorts='[[shorts]]\nname = "chorus"\nwide = true\n')
    config = project / "utavideo.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("enabled = false", "enabled = true"), encoding="utf-8"
    )
    _add_vertical_lines(
        project,
        "Dialogue: 0,0:00:00.53,0:00:01.77,VerticalBand,,0,0,0,,AA",
        # blur では歌詞を縦用 .ass に置いても描かない（本編の映像に入っているため）
        "Dialogue: 0,0:00:00.60,0:00:01.00,Lyrics,,0,0,0,,AAAA",
        # 区間の外の帯の行は描かない
        "Dialogue: 0,0:00:01.90,0:00:02.00,VerticalBand,,0,0,0,,OUT",
    )
    invoke("shorts", "-C", str(project))

    work = (project / "build/.work/shorts/chorus.ass").read_text(encoding="utf-8")
    assert work.count("Dialogue:") == 2
    assert "VerticalBand,,0,0,0,,AA" in work
    assert "OUT" not in work
    # 帯の文字（Vertical で始まるスタイル）には自動のフェードを入れない
    assert r"{\fad(150,150)}AA" not in work
    # 曲名表示は本編の映像ではなく、縦用 .ass の帯（自動で作るスタイル VerticalBand）に描く
    assert "VerticalBand,,0,0,0,,テスト / テスター" in work
    frame = (project / "build/.work/shorts/frame/chorus.ass").read_text(encoding="utf-8")
    assert "テスト / テスター" not in frame and "AAAA" in frame

    # vertical.overlay_text = false は、帯からも曲名表示を消す（wide には影響しない）
    config.write_text(
        config.read_text(encoding="utf-8").replace("[vertical]", "[vertical]\noverlay_text = false"),
        encoding="utf-8",
    )
    invoke("shorts", "-C", str(project))
    assert "テスト / テスター" not in (project / "build/.work/shorts/chorus.ass").read_text("utf-8")
    wide = (project / "build/.work/shorts/wide/chorus.ass").read_text("utf-8")
    assert "テスト / テスター" in wide


def test_check_for_a_blur_section_uses_the_main_lyrics(project: Path) -> None:
    _with_section(project, shorts='[[shorts]]\nname = "chorus"\n')
    _add_vertical_lines(
        project,
        "Style: VerticalBand,Test Sans,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,8,10,10,10,1",
        "Dialogue: 0,0:00:00.53,0:00:01.77,VerticalBand,,0,0,0,," + "A" * 20,
    )
    output = invoke("check", "-C", str(project)).output
    # 縦用 .ass に歌詞が無くても、区間の端は本編の .ass（0.20〜1.50 秒の行）で見る
    assert "区間の頭（0:00:00.530）が歌詞の行の途中にかかっています" in output
    # 帯に描く文字は、縦の画面に収まるか見る（blur で唯一、縦用 .ass から描く行のため）
    assert "「" + "A" * 20 + "」 が画面からはみ出しそうです" in output


def test_check_requires_the_band_style_for_blur_when_overlay_text_is_enabled(project: Path) -> None:
    """blur では曲名表示を帯（VerticalBand）に描くので、そのスタイルが無いとエラーになる。"""
    _with_section(project, shorts='[[shorts]]\nname = "chorus"\n')
    config = project / "utavideo.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("enabled = false", "enabled = true"), encoding="utf-8"
    )
    vertical = project / "src/vertical.ass"
    text = "\n".join(
        line
        for line in vertical.read_text(encoding="utf-8").splitlines()
        if "Style: VerticalBand," not in line
    )
    vertical.write_text(text + "\n", encoding="utf-8")

    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "VerticalBand" in result.output


def test_check_does_not_repeat_a_warning_for_overlapping_sections(project: Path) -> None:
    """複数のショートの区間に同時に入る行の警告は、1回だけ出す。"""
    _with_section(
        project,
        shorts='[[shorts]]\nname = "chorus"\n\n[[shorts]]\nname = "intro"\n',
    )
    _add_vertical_lines(
        project,
        "Comment: 0,0:00:00.53,0:00:01.77,Short,,0,0,0,,intro",
        "Style: VerticalBand,Test Sans,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,8,10,10,10,1",
        "Dialogue: 0,0:00:00.60,0:00:01.00,VerticalBand,,0,0,0,,{\\pos(90,40)}BAND",
    )
    output = invoke("check", "-C", str(project)).output
    assert output.count("\\pos / \\move を使っています") == 1


def test_check_rejects_a_video_size_taller_than_the_vertical_size(project: Path) -> None:
    """blur では、縦の幅に縮めた本編が縦の画面に収まらない設定を止める（黙って切らない）。"""
    _with_section(project, shorts='[[shorts]]\nname = "chorus"\n')
    config = project / "utavideo.toml"
    # video.size = [320, 180] を [180, 640] にすると、縦（180x320）より縦長になる
    config.write_text(
        config.read_text(encoding="utf-8").replace("size = [320, 180]", "size = [180, 640]"),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["check", "-C", str(project)])
    assert result.exit_code == 1
    assert "blur の画面を作れません" in result.output
    assert "180x640" in result.output and "180x320" in result.output


def test_preview_bg_vertical_for_blur_draws_the_main_video(project: Path) -> None:
    _with_shorts(project, shorts="")
    invoke("preview-bg", "-C", str(project))

    output = project / "build/preview/vertical-bg.mp4"
    video = _stream(_probe(output), "video")
    assert (video["width"], video["height"]) == (180, 320)
    # 下敷きにも本編の歌詞を焼き込む（完成図と同じ画面で、帯の文字を組めるようにする）
    frame = (project / "build/.work/vertical-preview-frame.ass").read_text(encoding="utf-8")
    assert "AAAA" in frame
    # 縦用 .ass の行は下敷きに焼き込まない（Aegisub で組むのはこちら）
    assert "AAAA" not in (project / "build/.work/vertical-preview.ass").read_text(encoding="utf-8")


def test_preview_bg_vertical_composites_layers_on_the_main_frame(project: Path) -> None:
    """blur（縦の下敷き）でも、本編と同じ画面（frame）に [[layers]] を重ねる。"""
    _with_shorts(project, shorts="")
    invoke("preview-bg", "-C", str(project))
    without_layer = _pixels(project / "build/preview/vertical-bg.mp4")

    (project / "src/layers").mkdir(parents=True, exist_ok=True)
    _make_logo(project / "src/layers/logo.png", (40, 20), "0x00FF00")
    toml = (project / "utavideo.toml").read_text(encoding="utf-8")
    toml += '\n[[layers]]\nname = "logo"\nfile = "src/layers/logo.png"\n'
    (project / "utavideo.toml").write_text(toml, encoding="utf-8")
    invoke("preview-bg", "-C", str(project))
    with_layer = _pixels(project / "build/preview/vertical-bg.mp4")

    assert without_layer != with_layer


@pytest.mark.skipif(rubberband_filter_error() is not None, reason="rubberband 付きの ffmpeg が必要")
def test_inst_writes_one_video_per_key_without_lyrics(project: Path) -> None:
    invoke("inst", "-C", str(project), "--keys", "-1,2")

    minus_one, plus_two = project / "build/inst/test-key-1.mp4", project / "build/inst/test-key+2.mp4"
    for output in (minus_one, plus_two):
        video, audio = _stream(_probe(output), "video"), _stream(_probe(output), "audio")
        assert (video["codec_name"], video["width"], video["height"]) == ("h264", 320, 180)
        assert audio["codec_name"] == "aac"
    # 歌詞は焼かず、曲名表示（{title} / {artist}（Key: ...））だけを描く
    assert _pixels(minus_one) != _pixels(plus_two)  # キーごとに違う文字が描かれている
    ass = (project / "build/.work/inst/key-1.ass").read_text(encoding="utf-8")
    assert "AAAA" not in ass  # 歌詞の行は含まれない
    assert "Key: -1" in ass
    # ピッチを変えるだけなので、キーが違っても長さは変わらない
    assert float(_probe(minus_one)["format"]["duration"]) == pytest.approx(
        float(_probe(plus_two)["format"]["duration"]), abs=0.05
    )


@pytest.mark.skipif(rubberband_filter_error() is not None, reason="rubberband 付きの ffmpeg が必要")
def test_inst_defaults_to_key_zero(project: Path) -> None:
    invoke("inst", "-C", str(project))
    assert (project / "build/inst/test-key0.mp4").is_file()


def test_inst_requires_its_own_audio_setting(project: Path) -> None:
    config = (project / "utavideo.toml").read_text(encoding="utf-8")
    (project / "utavideo.toml").write_text(
        config.replace('[inst]\naudio = "src/mix/inst.wav"\n', ""), encoding="utf-8"
    )

    result = runner.invoke(app, ["inst", "-C", str(project)])
    assert result.exit_code == 1
    assert "inst.audio が設定されていません" in result.output
    assert not (project / "build/inst").exists()


@pytest.mark.skipif(rubberband_filter_error() is not None, reason="rubberband 付きの ffmpeg が必要")
def test_inst_uses_its_own_audio_not_the_main_track(project: Path) -> None:
    """本編は 440Hz、inst.audio は 220Hz のサイン波（project フィクスチャ）。音を聞き分けて確かめる。"""
    invoke("inst", "-C", str(project))
    output = project / "build/inst/test-key0.mp4"

    near_220 = _mean_volume_db(output, band=(190, 260))
    near_440 = _mean_volume_db(output, band=(410, 470))
    # 本編（440Hz）を使っていれば near_440 の方が大きいはずだが、inst.audio（220Hz）を使うので逆になる
    assert near_220 > near_440 + 5


@pytest.mark.skipif(rubberband_filter_error() is not None, reason="rubberband 付きの ffmpeg が必要")
def test_inst_records_inputs_per_key_and_status_shows_them_as_clean(project: Path) -> None:
    invoke("inst", "-C", str(project), "--keys", "-1,2")

    assert (project / "build/.work/inst-key-1-inputs.json").is_file()
    assert (project / "build/.work/inst-key+2-inputs.json").is_file()
    assert "inst " not in invoke("status", "-C", str(project)).output


def test_inst_falls_back_to_atempo_when_rubberband_is_unavailable(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # asetrate/atempo は組み込みフィルタなので、rubberband の有無に関わらず実行できる
    monkeypatch.setattr(cli, "rubberband_filter_error", lambda: "テスト用に無効化")

    result = invoke("inst", "-C", str(project), "--keys", "-1,2")

    assert "asetrate" in result.output or "atempo" in result.output
    minus_one, plus_two = project / "build/inst/test-key-1.mp4", project / "build/inst/test-key+2.mp4"
    assert minus_one.is_file() and plus_two.is_file()
    assert float(_probe(minus_one)["format"]["duration"]) == pytest.approx(
        float(_probe(plus_two)["format"]["duration"]), abs=0.05
    )


def test_inst_measures_loudness_once_for_all_keys(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    original = measure_loudness

    def counting(audio: Path, target: LoudnormTarget | None = None) -> LoudnormMeasurement:
        calls.append(audio)
        return original(audio, target)

    monkeypatch.setattr(cli, "measure_loudness", counting)
    monkeypatch.setattr(cli, "rubberband_filter_error", lambda: "テスト用に無効化")

    invoke("inst", "-C", str(project), "--keys", "-1,0,2")

    assert len(calls) == 1


@pytest.mark.skipif(rubberband_filter_error() is not None, reason="rubberband 付きの ffmpeg が必要")
def test_inst_normalizes_loudness_to_the_target(project: Path) -> None:
    invoke("inst", "-C", str(project))

    measured = measure_loudness(project / "build/inst/test-key0.mp4")
    assert float(measured.input_i) == pytest.approx(-16.0, abs=1.0)


def test_inst_with_lyrics_option_includes_the_lyrics_line(project: Path) -> None:
    invoke("inst", "-C", str(project), "--lyrics")

    ass = (project / "build/.work/inst/key0.ass").read_text(encoding="utf-8")
    assert "AAAA" in ass  # 歌詞の行が含まれる
    assert "Key: 0" in ass  # 曲名表示も共存する
    assert r"\fad(150,150)" in ass  # 本編と同じ自動フェードが入る（既定の config.lyrics.fade_ms）


def test_inst_with_lyrics_and_multiple_keys_keeps_duration(project: Path) -> None:
    invoke("inst", "-C", str(project), "--lyrics", "--keys", "-1,2")

    minus_one, plus_two = project / "build/inst/test-key-1.mp4", project / "build/inst/test-key+2.mp4"
    assert minus_one.is_file() and plus_two.is_file()
    assert float(_probe(minus_one)["format"]["duration"]) == pytest.approx(
        float(_probe(plus_two)["format"]["duration"]), abs=0.05
    )


def test_inst_with_lyrics_reports_undefined_style_error(project: Path) -> None:
    lyrics = LYRICS.format(font="Test Sans").replace("Lyrics,,0,0,0,,AAAA", "Nope,,0,0,0,,AAAA")
    (project / "src/lyrics.ass").write_text(lyrics, encoding="utf-8")

    result = runner.invoke(app, ["inst", "-C", str(project), "--lyrics"])
    assert result.exit_code == 1
    assert "未定義のスタイル" in result.output

    # --lyrics を付けなければ歌詞の中身は見ないので、同じ .ass でも通る
    assert invoke("inst", "-C", str(project)).exit_code == 0


def test_inst_with_lyrics_reports_overflowing_line(project: Path) -> None:
    long_line = "Dialogue: 0,0:00:00.20,0:00:01.50,Lyrics,,0,0,0,," + "A" * 20
    lyrics = LYRICS.format(font="Test Sans") + long_line + "\n"
    (project / "src/lyrics.ass").write_text(lyrics, encoding="utf-8")

    result = runner.invoke(app, ["inst", "-C", str(project), "--lyrics"])
    assert "「" + "A" * 20 + "」 が画面からはみ出しそうです" in result.output

    # --lyrics を付けなければ、はみ出しの検査もしない
    assert "はみ出しそう" not in invoke("inst", "-C", str(project)).output


# 音符・休符・タイ・拍子変更を含む、[inst.score] の検証専用の最小の楽譜（issue #143）
_SCORE_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Vocal</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <direction><sound tempo="120"/></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
"""


# 音符が1個しか無い（issue #143: score_scroll_filterが要求する2点に満たない）楽譜
_SINGLE_NOTE_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Vocal</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>2</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>8</duration><voice>1</voice><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
"""


def _make_mscz(tmp_path: Path, musicxml: str, name: str) -> Path:
    """MuseScore CLIでその場限りの.msczを作る（バイナリのfixtureは固定コミットしない。issue #140と同じ）。"""
    musescore = score.require_musescore()
    musicxml_path = tmp_path / f"{name}.musicxml"
    musicxml_path.write_text(musicxml, encoding="utf-8")
    mscz_path = tmp_path / f"{name}.mscz"
    subprocess.run([musescore, "-o", str(mscz_path), str(musicxml_path)], check=True, capture_output=True)
    return mscz_path


@pytest.fixture
def mscz_file(tmp_path: Path) -> Path:
    return _make_mscz(tmp_path, _SCORE_MUSICXML, "score")


@pytest.mark.skipif(score.find_musescore() is None, reason="MuseScore 4 が無い環境の確認用")
def test_inst_reports_missing_score_file(project: Path) -> None:
    """MuseScore 4 が無くても、.msczのファイル自体が無いことは検出できる。"""
    (project / "utavideo.toml").write_text(
        TOML.format(background="bg.png") + '[inst.score]\nfile = "src/no-such-file.mscz"\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["inst", "-C", str(project)])
    assert result.exit_code == 1
    assert "inst.score.file のファイルがありません" in result.output


@pytest.mark.skipif(score.find_musescore() is None, reason="MuseScore 4 が必要")
def test_inst_reports_a_score_with_fewer_than_two_notes(project: Path, tmp_path: Path) -> None:
    """score_scroll_filterは2点以上を要求するので、音符が1個しか無い楽譜は検査エラーにする。"""
    mscz = _make_mscz(tmp_path, _SINGLE_NOTE_MUSICXML, "single-note")
    (project / "utavideo.toml").write_text(
        TOML.format(background="bg.png") + f'[inst.score]\nfile = "{mscz.as_posix()}"\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["inst", "-C", str(project)])
    assert result.exit_code == 1
    assert "音符が2個未満しかなく" in result.output


def _row_bytes(video: Path, *, at: float, y: int, width: int) -> bytes:
    """指定した時刻のフレームを読み、y行目だけ切り出す（ffmpegからは1フレーム全体で受け取る）。"""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr.decode(errors="replace")
    return out.stdout[y * width : (y + 1) * width]


@pytest.mark.skipif(score.find_musescore() is None, reason="MuseScore 4 が必要")
def test_inst_composites_the_score_scroll(project: Path, mscz_file: Path) -> None:
    """[inst.score] を設定すると、楽譜が横スクロールで重なった動画が書き出せる。"""
    without_score = project / "build/inst/test-key0.mp4"
    invoke("inst", "-C", str(project))
    row_without_score = _row_bytes(without_score, at=0.5, y=20, width=320)
    without_score.unlink()

    (project / "utavideo.toml").write_text(
        TOML.format(background="bg.png") + f'[inst.score]\nfile = "{mscz_file.as_posix()}"\ny = 20\n',
        encoding="utf-8",
    )
    result = invoke("inst", "-C", str(project))
    assert result.exit_code == 0

    output = project / "build/inst/test-key0.mp4"
    assert output.is_file()
    assert (project / "build/.work/inst/score.png").is_file()  # 楽譜のPNGがwork_dirに書き出されている

    # 楽譜の帯（y=20）が、楽譜を重ねなかったときと違う絵になっている（=何か描かれた）ことを確かめる
    row_with_score = _row_bytes(output, at=0.5, y=20, width=320)
    assert row_with_score != row_without_score
