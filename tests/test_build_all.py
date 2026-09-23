"""build-all（対象外/要対応/済み/実行の判定と表示）。ffmpeg は build の実行以外では要らない。"""

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import MakeFont
from utavideo import build_all, inputs
from utavideo.analyze import Analysis, FontSearch, ThumbnailAnalysis
from utavideo.build_all import Plan, TargetStatus
from utavideo.cli import app
from utavideo.ffmpeg import subtitles_filter_error
from utavideo.project import Project, scaffold

requires_libass = pytest.mark.skipif(
    subtitles_filter_error() is not None, reason="libass 付きの ffmpeg が必要"
)

runner = CliRunner()

TOML = """
[song]
title = "曲"
[audio]
file = "src/mix/曲 v1.2.wav"
[video]
background = "src/bg/bg.png"
"""

THUMBNAIL_ASS = """[Script Info]
PlayResX: 90
PlayResY: 90
"""

STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
LYRICS = f"""[Script Info]
PlayResX: 64
PlayResY: 36

[V4+ Styles]
{STYLE_FORMAT}
Style: Lyrics,Test Sans,10,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,2,2,2,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.10,0:00:00.50,Lyrics,,0,0,0,,A
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    root = tmp_path / "曲"
    scaffold(root, "曲", "曲")
    (root / "utavideo.toml").write_text(TOML, encoding="utf-8")
    # background_issues はファイルの有無と拡張子だけを見るので、中身は本物の画像でなくてよい
    (root / "src/bg").mkdir(parents=True, exist_ok=True)
    (root / "src/bg/bg.png").write_bytes(b"not a real png")
    return root


def _search() -> FontSearch:
    return FontSearch.load()


def _write_thumbnails_config(project: Path, extra: str = "") -> None:
    config = TOML + f'[[thumbnails]]\nname = "main"\nfile = "src/thumbnail.ass"\nsize = [90, 90]\n{extra}'
    (project / "utavideo.toml").write_text(config, encoding="utf-8")
    (project / "src/thumbnail.ass").write_text(THUMBNAIL_ASS, encoding="utf-8")


def test_project_without_thumbnails_excludes_the_target(project: Path) -> None:
    plan = build_all.collect(Project.load(project), _search())
    assert not any(t.name.startswith("thumbnail") for t in plan.targets)


def test_project_without_audio_reports_build_as_needing_attention(project: Path) -> None:
    # audio.file・video.background のファイルが無いので、build は要対応になる
    plan = build_all.collect(Project.load(project), _search())
    build = next(t for t in plan.targets if t.name == "build")
    assert build.state == "issues"
    assert any("audio.file のファイルがありません" in message for message in build.issues)


def test_description_and_announce_run_without_extra_config(project: Path) -> None:
    # [description]・[announce]・[[uploads]] が無くても、既定の書式でいつも実行し直す
    plan = build_all.collect(Project.load(project), _search())
    description = next(t for t in plan.targets if t.name == "description")
    announce = next(t for t in plan.targets if t.name == "announce")
    assert description.state == "run"
    assert (
        Project.load(project).title_output,
        Project.load(project).description_output,
    ) == description.outputs
    assert announce.state == "run"


def test_description_reports_issues_from_lint(project: Path) -> None:
    # description.title を直書きした値はそのまま使われ、書式の誤りは自動組み立てのときだけ起きる
    # （ユーザー設定の書式が壊れているケース）。[description] があるときだけ lint する
    config = TOML + '[description]\ntext = "本文"\n'
    (project / "utavideo.toml").write_text(config, encoding="utf-8")
    config_dir = project.parents[0] / "config" / "utavideo"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text('[description]\ntitle = "{unknown}"\n', encoding="utf-8")

    plan = build_all.collect(Project.load(project), _search())
    description = next(t for t in plan.targets if t.name == "description")
    assert description.state == "issues"
    assert description.issues


def test_announce_reports_issues_from_lint_but_not_missing_uploads(project: Path) -> None:
    # uploads が無いことは警告どまりで、要対応にはしない（既存の announce コマンドと同じ）
    config = TOML + '[announce]\nhashtags = ["a-b"]\n'  # X でタグが切れる文字を含む
    (project / "utavideo.toml").write_text(config, encoding="utf-8")
    plan = build_all.collect(Project.load(project), _search())
    announce = next(t for t in plan.targets if t.name == "announce")
    assert announce.state == "issues"
    assert any("a-b" in message for message in announce.issues)


def test_thumbnail_reports_a_missing_file_as_needing_attention(project: Path) -> None:
    # src/thumbnail-sub.ass はまだ無いファイル（scaffold が作る既定の src/thumbnail.ass とは別）
    config = TOML + '[[thumbnails]]\nname = "sub"\nfile = "src/thumbnail-sub.ass"\nsize = [90, 90]\n'
    (project / "utavideo.toml").write_text(config, encoding="utf-8")
    plan = build_all.collect(Project.load(project), _search())
    thumb = next(t for t in plan.targets if t.name == "thumbnail:sub")
    assert thumb.state == "issues"
    assert any("file のファイルがありません" in message for message in thumb.issues)


def test_thumbnail_runs_when_the_output_is_missing_and_skips_once_it_exists(project: Path) -> None:
    _write_thumbnails_config(project)
    loaded = Project.load(project)
    plan = build_all.collect(loaded, _search())
    thumb = next(t for t in plan.targets if t.name == "thumbnail:main")
    assert thumb.state == "run"
    assert thumb.outputs == (loaded.build_dir / "thumbnail" / "main.png",)

    (loaded.build_dir / "thumbnail").mkdir(parents=True, exist_ok=True)
    (loaded.build_dir / "thumbnail" / "main.png").write_bytes(b"png")
    plan = build_all.collect(loaded, _search())
    thumb = next(t for t in plan.targets if t.name == "thumbnail:main")
    assert thumb.state == "skip"


def _record_build(project: Path) -> None:
    """build が書き出し終えたときの記録を、ffmpeg を使わずに作る（tests/test_status.py と同じ）。"""
    (project / "build").mkdir(exist_ok=True)
    (project / "build/main.mp4").write_bytes(b"video")
    loaded = Project.load(project)
    record = inputs.record_text(loaded, inputs.with_fonts(inputs.snapshot(loaded), ()))
    loaded.inputs_record.parent.mkdir(parents=True, exist_ok=True)
    loaded.inputs_record.write_text(record, encoding="utf-8")


def _no_issues_analysis(*_: object, **__: object) -> Analysis:
    return Analysis([], 1.0, None, ())


def test_build_runs_when_missing_and_skips_once_up_to_date(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(build_all, "analyze", _no_issues_analysis)
    loaded = Project.load(project)

    plan = build_all.collect(loaded, _search())
    assert next(t for t in plan.targets if t.name == "build").state == "run"

    _record_build(project)
    plan = build_all.collect(Project.load(project), _search())
    assert next(t for t in plan.targets if t.name == "build").state == "skip"


def test_build_is_stale_after_a_recorded_build(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_all, "analyze", _no_issues_analysis)
    _record_build(project)
    lyrics = project / "src/lyrics.ass"
    later = (project / "build/main.mp4").stat().st_mtime + 10
    lyrics.write_text(lyrics.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    os.utime(lyrics, (later, later))

    plan = build_all.collect(Project.load(project), _search())
    assert next(t for t in plan.targets if t.name == "build").state == "run"


def test_render_groups_by_state() -> None:
    plan = Plan(
        (
            TargetStatus(
                "description", "run", outputs=(Path("build/title.txt"), Path("build/description.txt"))
            ),
            TargetStatus("announce", "skip", outputs=(Path("build/announce.txt"),)),
            TargetStatus(
                "thumbnail:sub", "issues", issues=("サムネイル sub: file のファイルがありません: x",)
            ),
        )
    )
    text = build_all.render(plan)
    assert text == (
        "実行しました:\n"
        "  description: build/title.txt, build/description.txt\n"
        "\n"
        "スキップ（済み）:\n"
        "  announce: build/announce.txt\n"
        "\n"
        "要対応:\n"
        "  thumbnail:sub: サムネイル sub: file のファイルがありません: x"
    )


def test_render_reports_multiple_issue_lines_for_one_target() -> None:
    plan = Plan((TargetStatus("build", "issues", issues=("問題1", "問題2")),))
    text = build_all.render(plan)
    assert text == "要対応:\n  build: 問題1\n  build: 問題2"


def test_render_is_clean_when_there_is_nothing_left() -> None:
    assert build_all.render(Plan(())) == "クリーンです（作るものはありません）"


@requires_libass
def test_build_all_command_writes_everything_and_skips_on_the_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_font: MakeFont
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    font_dir = tmp_path / "fonts"
    make_font(font_dir / "TestSans.ttf", "Test Sans")
    monkeypatch.setenv("UTAVIDEO_FONT_DIRS", str(font_dir))

    root = tmp_path / "song"
    scaffold(root, "テスト", "test")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         str(root / "src/mix/test-v1.0.wav")],
        check=True,
    )  # fmt: skip
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x36",
         "-frames:v", "1", str(root / "src/bg/bg.png")],
        check=True,
    )  # fmt: skip
    (root / "utavideo.toml").write_text(
        """
[song]
title = "テスト"
slug = "test"
[audio]
file = "src/mix/test-v1.0.wav"
[video]
background = "src/bg/bg.png"
size = [64, 36]
fps = 10
preset = "ultrafast"
[overlay_text]
enabled = false
""",
        encoding="utf-8",
    )
    (root / "src/lyrics.ass").write_text(LYRICS, encoding="utf-8")

    first = runner.invoke(app, ["build-all", "-C", str(root)])
    assert first.exit_code == 0, first.output
    assert "実行しました" in first.output
    assert "build: " in first.output
    assert (root / "build/main.mp4").is_file()
    assert (root / "build/title.txt").is_file()
    assert (root / "build/description.txt").is_file()
    assert (root / "build/announce.txt").is_file()

    second = runner.invoke(app, ["build-all", "-C", str(root)])
    assert second.exit_code == 0, second.output
    assert "スキップ（済み）" in second.output
    assert "build: " in second.output.split("スキップ（済み）")[1]
    # description・announce は済み判定が無いので、毎回「実行しました」に載る
    assert "実行しました" in second.output
    assert "description: " in second.output.split("実行しました")[1].split("スキップ")[0]


@requires_libass
def test_build_all_prints_warnings_when_writing_description_and_announce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # collect() はエラーの有無しか見ないので、警告（materials.files が無い・uploads が無い）は
    # 実際に書き出すとき（_run_build_all_target）にもう一度検査して表示する必要がある
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    root = tmp_path / "song"
    scaffold(root, "テスト", "test")
    (root / "utavideo.toml").write_text(
        """
[song]
title = "テスト"
slug = "test"
[audio]
file = "src/mix/missing.wav"
[video]
background = "src/bg/missing.png"

[description]
text = "本文"

[[materials]]
section = "素材"
files = ["missing.png"]
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["build-all", "-C", str(root)])
    assert result.exit_code == 0, result.output
    # build は audio.file が無いので要対応（実行しない）
    assert "audio.file のファイルがありません" in result.output
    assert "materials.files のファイルがありません" in result.output
    assert "リンクがありません" in result.output


@requires_libass
def test_thumbnail_execution_stops_build_all_if_a_recheck_finds_a_real_error(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # collect() の判定と、実際に書き出す直前のもう一度の検査の間に対象が壊れる（今回はテストのため
    # collect 側だけ偽装する）ケースの回帰テスト。書き出さずに exit code 1 で止まるべき
    config = TOML + '[[thumbnails]]\nname = "main"\nfile = "src/thumbnail-missing.ass"\nsize = [90, 90]\n'
    (project / "utavideo.toml").write_text(config, encoding="utf-8")
    monkeypatch.setattr(build_all, "analyze_thumbnails", lambda *a, **k: ThumbnailAnalysis([], {}))

    loaded = Project.load(project)
    plan = build_all.collect(loaded, _search())
    thumb = next(t for t in plan.targets if t.name == "thumbnail:main")
    assert thumb.state == "run"  # 偽装により「問題なし」に見えている

    result = runner.invoke(app, ["build-all", "-C", str(project)])
    assert result.exit_code == 1, result.output
    assert "file のファイルがありません" in result.output
    assert not (loaded.build_dir / "thumbnail" / "main.png").exists()
