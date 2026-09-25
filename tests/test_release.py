"""release の採番と入力の比較。動画の中身は問わないので ffmpeg は要らない。"""

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import scaffold_named_project
from utavideo import inputs
from utavideo import project as project_module
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


def test_records_the_match_after_creating_a_release(project: Path) -> None:
    assert _release(project).exit_code == 0

    record = json.loads((project / "build/.work/release-match.json").read_text(encoding="utf-8"))
    assert record["version"] == "v1.2"
    assert record["matched"] == "曲-v1.2.0.mp4"


def test_records_the_match_when_stopping_for_the_same_content(project: Path) -> None:
    (project / "release/曲-v1.2.0.mp4").write_bytes(b"video")

    result = _release(project)
    assert result.exit_code == 1
    record = json.loads((project / "build/.work/release-match.json").read_text(encoding="utf-8"))
    assert record["matched"] == "曲-v1.2.0.mp4"


def test_later_calls_use_the_recorded_match_instead_of_rereading_release(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _release(project).exit_code == 0

    def fail_if_called(*args: object, **kwargs: object) -> bool:
        raise AssertionError("記録を使わず release/ を読み直した")

    monkeypatch.setattr(project_module.filecmp, "cmp", fail_if_called)
    result = _release(project)
    assert result.exit_code == 1
    assert "同じ内容が既にあります" in result.output


def test_rereads_release_after_main_changes(project: Path) -> None:
    assert _release(project).exit_code == 0

    main = project / "build/main.mp4"
    main.write_bytes(b"different content")
    later = main.stat().st_mtime + 10
    os.utime(main, (later, later))

    assert _release(project).exit_code == 0
    assert _released(project) == ["曲-v1.2.0.mp4", "曲-v1.2.1.mp4"]


def test_ignores_the_recorded_match_if_that_file_was_removed(project: Path) -> None:
    assert _release(project).exit_code == 0
    (project / "release/曲-v1.2.0.mp4").unlink()

    result = _release(project)
    assert result.exit_code == 0
    assert _released(project) == ["曲-v1.2.0.mp4"]


def test_counts_uppercase_extension(project: Path) -> None:
    (project / "release/曲-v1.2.3.MP4").write_bytes(b"other")
    assert _release(project).exit_code == 0
    assert "曲-v1.2.4.mp4" in _released(project)


def test_numbers_continue_from_videos_released_before_slug(project: Path) -> None:
    # song.slug より前の名前（曲名と空白区切り）で公開した動画の続きから数える
    (project / "release/曲 v1.2.0.mp4").write_bytes(b"other")
    assert _release(project).exit_code == 0
    assert _released(project) == ["曲 v1.2.0.mp4", "曲-v1.2.1.mp4"]


def test_writes_only_the_video_and_ignores_texts_in_release(project: Path) -> None:
    # 概要欄は build/ にだけ置く。release/ に残った .txt は数えず、書き換えず、止まる理由にもしない
    _write_toml(project, TOML + DESCRIPTION)
    (project / "release/曲-v1.2.0.txt").write_text("前の動画の概要欄", encoding="utf-8")
    (project / "release/曲-v1.2.5.txt").write_text("消した動画の概要欄", encoding="utf-8")

    result = _release(project)
    assert result.exit_code == 0, result.output
    assert _released(project) == ["曲-v1.2.0.mp4", "曲-v1.2.0.txt", "曲-v1.2.5.txt"]
    assert (project / "release/曲-v1.2.0.txt").read_text(encoding="utf-8") == "前の動画の概要欄"


def _record_build(project: Path, font_files: tuple[Path, ...] = ()) -> None:
    """build が書き出し終えたときの記録を、ffmpeg を使わずに作る。"""
    loaded = Project.load(project)
    target = inputs.main_target(loaded)
    record = inputs.record_text(target, inputs.with_fonts(inputs.snapshot(target), font_files))
    target.record_path.parent.mkdir(parents=True, exist_ok=True)
    target.record_path.write_text(record, encoding="utf-8")


def _edit_later(project: Path, rel: str, text: str) -> None:
    """build/main.mp4 より新しい更新時刻で書く。"""
    path = project / rel
    path.write_text(text, encoding="utf-8")
    later = (project / "build/main.mp4").stat().st_mtime + 10
    os.utime(path, (later, later))


REORDERED = """
# コメントと並び順、書き方の違いは比べない
[video]
background = 'src/bg/bg.png'
[audio]
file = "src/mix/曲 v1.2.wav"
[song]
title = "曲"
slug = "kyoku"
original_urls = ["https://example.com/"]
[[credits]]
roles = ["Vocal"]
name = "名前"
[[materials]]
section = "イラスト"
"""


def test_changes_that_do_not_affect_the_video_do_not_stop(project: Path) -> None:
    _record_build(project)
    _edit_later(project, "utavideo.toml", REORDERED + DESCRIPTION)
    lyrics = (project / "src/lyrics.ass").read_text(encoding="utf-8")
    _edit_later(project, "src/lyrics.ass", lyrics)  # 保存し直しただけ

    result = _release(project)
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    ("before", "after"),
    [('title = "曲"', 'title = "曲名"'), ("[video]", '[overlay_text]\ntext = "{title}"\n[video]')],
)
def test_stops_when_a_rendered_setting_changes(project: Path, before: str, after: str) -> None:
    _record_build(project)
    _edit_later(project, "utavideo.toml", TOML.replace(before, after))

    result = _release(project)
    assert result.exit_code == 1
    assert "変わった入力があります（utavideo.toml）" in result.output
    assert _release(project, "--allow-stale").exit_code == 0


def test_stops_when_lyrics_content_changes(project: Path) -> None:
    _record_build(project)
    lyrics = project / "src/lyrics.ass"
    lyrics.write_text(lyrics.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    result = _release(project)
    assert result.exit_code == 1
    assert "（lyrics.file）" in result.output


def test_stops_when_a_used_font_file_changes(project: Path, tmp_path: Path) -> None:
    font = tmp_path / "fonts/font.ttf"
    font.parent.mkdir()
    font.write_bytes(b"font")
    _record_build(project, (font,))
    assert _release(project).exit_code == 0

    font.write_bytes(b"other font")
    result = _release(project, "--version", "v2.0")
    assert result.exit_code == 1
    assert "（フォント）" in result.output


NAMED_TOML = """
[song]
title = "曲"
[audio]
file = "src/mix/曲 v1.2.wav"
[video]
background = "src/bg/bg.png"

[[shorts]]
name = "chorus"
"""


def _scaffold_shorts_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, toml: str = NAMED_TOML) -> Path:
    return scaffold_named_project(tmp_path, monkeypatch, toml)


def _release_short(project: Path, name: str = "chorus", *args: str):
    return runner.invoke(app, ["release", "-C", str(project), "--short", name, *args])


def _record_shorts_build(project: Path) -> None:
    """build/shorts/chorus.mp4 が書き出し終えたときの記録を、ffmpeg を使わずに作る。"""
    loaded = Project.load(project)
    short = loaded.config.shorts[0]
    target = inputs.shorts_target(loaded, short)
    target.output.parent.mkdir(parents=True, exist_ok=True)
    target.output.write_bytes(b"short video")
    record = inputs.record_text(target, inputs.snapshot(target))
    target.record_path.parent.mkdir(parents=True, exist_ok=True)
    target.record_path.write_text(record, encoding="utf-8")


def test_short_release_starts_at_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _scaffold_shorts_project(tmp_path, monkeypatch)
    _record_shorts_build(root)

    assert _release_short(root).exit_code == 0
    assert _released(root) == ["曲-shorts-chorus-v1.2.0.mp4"]


def test_short_release_numbers_are_independent_from_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _scaffold_shorts_project(tmp_path, monkeypatch)
    (root / "build/main.mp4").write_bytes(b"video")
    _record_shorts_build(root)

    assert _release(root).exit_code == 0
    assert _release_short(root).exit_code == 0
    assert _released(root) == ["曲-shorts-chorus-v1.2.0.mp4", "曲-v1.2.0.mp4"]


def test_short_release_fails_for_an_unknown_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _scaffold_shorts_project(tmp_path, monkeypatch)
    _record_shorts_build(root)

    result = _release_short(root, "missing")
    assert result.exit_code == 1
    assert "chorus" in result.output


def test_short_release_stops_when_not_built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _scaffold_shorts_project(tmp_path, monkeypatch)

    result = _release_short(root)
    assert result.exit_code == 1
    assert "build/shorts/chorus.mp4 がありません" in result.output
    assert "utavideo shorts --name chorus" in result.output


def test_short_release_stops_when_vertical_ass_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _scaffold_shorts_project(tmp_path, monkeypatch)
    _record_shorts_build(root)

    vertical = root / "src/vertical.ass"
    later = (root / "build/shorts/chorus.mp4").stat().st_mtime + 10
    vertical.write_text(vertical.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    os.utime(vertical, (later, later))

    result = _release_short(root)
    assert result.exit_code == 1
    assert "vertical.lyrics" in result.output
    assert _release_short(root, "chorus", "--allow-stale").exit_code == 0


def test_wide_short_release_copies_both_with_separate_numbering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = NAMED_TOML.replace('name = "chorus"', 'name = "chorus"\nwide = true')
    root = _scaffold_shorts_project(tmp_path, monkeypatch, toml)
    _record_shorts_build(root)
    wide_output = root / "build/shorts/wide/chorus.mp4"
    wide_output.parent.mkdir(parents=True, exist_ok=True)
    wide_output.write_bytes(b"wide video")

    assert _release_short(root).exit_code == 0
    assert _released(root) == ["曲-shorts-chorus-v1.2.0.mp4", "曲-shorts-chorus-wide-v1.2.0.mp4"]


def test_record_of_another_video_falls_back_to_modification_times(project: Path) -> None:
    # 記録の後に build/main.mp4 が差し替わっていたら、記録は使わない
    _record_build(project)
    (project / "build/main.mp4").write_bytes(b"replaced")
    _edit_later(project, "utavideo.toml", TOML + DESCRIPTION)

    result = _release(project)
    assert result.exit_code == 1
    assert "build/main.mp4 より新しい入力があります（utavideo.toml）" in result.output
