"""new / init の引数と既定値、サムネイルの検査。"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from utavideo import subs
from utavideo.cli import analyze_thumbnails, app
from utavideo.config import load_project_config
from utavideo.ffmpeg import FFmpegError
from utavideo.project import Project

runner = CliRunner()


def test_new_uses_the_path_as_is_and_takes_the_slug_from_it(tmp_path: Path) -> None:
    root = tmp_path / "work" / "20260916-my-song"
    result = runner.invoke(app, ["new", str(root)])

    assert result.exit_code == 0, result.output
    song = load_project_config(root / "utavideo.toml").song
    # 端末ではないので聞かずに既定値。日付はフォルダ名に書いた分だけで、utavideo は足さない
    assert song.slug == "my-song"
    assert song.title == "my-song"
    assert song.artist == ""


def test_new_writes_the_given_values(tmp_path: Path) -> None:
    root = tmp_path / "20260916-song"
    result = runner.invoke(
        app, ["new", str(root), "--title", "星の歌", "--artist", "歌手", "--slug", "hoshi"]
    )

    assert result.exit_code == 0, result.output
    song = load_project_config(root / "utavideo.toml").song
    assert (song.title, song.artist, song.slug) == ("星の歌", "歌手", "hoshi")
    # ファイル名は曲名ではなく slug から作るので、後で曲名を直しても変わらない
    assert load_project_config(root / "utavideo.toml").audio.file == Path("src/mix/hoshi-v1.0.wav")


def test_new_stops_before_creating_anything_when_the_name_is_unusable(tmp_path: Path) -> None:
    root = tmp_path / "CON"
    result = runner.invoke(app, ["new", str(root)])

    assert result.exit_code == 1
    assert not root.exists()


def test_init_takes_the_slug_from_an_existing_folder_name(tmp_path: Path) -> None:
    root = tmp_path / "20260913 制作中の曲"
    root.mkdir()
    result = runner.invoke(app, ["init", str(root), "--artist", "歌手"])

    assert result.exit_code == 0, result.output
    song = load_project_config(root / "utavideo.toml").song
    assert song.slug == "制作中の曲"
    assert song.title == "制作中の曲"


def test_new_hints_at_the_date_prefix_but_creates_the_folder(tmp_path: Path) -> None:
    root = tmp_path / "song"
    result = runner.invoke(app, ["new", str(root)])

    assert result.exit_code == 0, result.output
    assert "ヒント" in result.output
    assert (root / "utavideo.toml").is_file()


def test_new_says_nothing_extra_for_a_dated_folder(tmp_path: Path) -> None:
    result = runner.invoke(app, ["new", str(tmp_path / "20260916-song")])

    assert result.exit_code == 0, result.output
    assert "ヒント" not in result.output


def test_init_in_a_configured_folder_explains_how_to_add_a_thumbnail(tmp_path: Path) -> None:
    root = tmp_path / "20260916-song"
    assert runner.invoke(app, ["new", str(root)]).exit_code == 0
    config = (root / "utavideo.toml").read_text(encoding="utf-8")
    (root / "src/thumbnail.ass").unlink()

    # [[thumbnails]] がある曲では、案内しない
    result = runner.invoke(app, ["init", str(root)])
    assert result.exit_code == 0, result.output
    assert "[[thumbnails]]" not in result.output
    assert not (root / "src/thumbnail.ass").exists()

    (root / "utavideo.toml").write_text(config.split("[[thumbnails]]")[0], encoding="utf-8")
    result = runner.invoke(app, ["init", str(root)])
    assert result.exit_code == 0, result.output
    assert "[[thumbnails]]" in result.output
    assert not (root / "src/thumbnail.ass").exists()


def test_unreadable_background_becomes_an_issue_instead_of_stopping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "utavideo.toml").write_text(
        '[song]\ntitle = "曲"\n[audio]\nfile = "a.wav"\n[video]\nbackground = "bg.mp4"\n'
        '[[thumbnails]]\nname = "main"\nfile = "t.ass"\nat = "0:01"\n',
        encoding="utf-8",
    )
    (tmp_path / "bg.mp4").write_bytes(b"not a video")

    def unreadable(path: Path) -> float:
        raise FFmpegError(f"{path} を読めません")

    monkeypatch.setattr("utavideo.cli.probe_duration", unreadable)
    project = Project.load(tmp_path)
    issues = analyze_thumbnails(project, project.config.thumbnails, bg_only=True).issues

    # 背景の長さの警告を重ねず、読めないエラーを1件だけ出す
    assert len(issues) == 1
    assert issues[0].level == "error" and "を読めません" in issues[0].message


def test_vertical_ass_creates_the_file_once_and_keeps_the_source(tmp_path: Path) -> None:
    root = tmp_path / "20260916-song"
    assert runner.invoke(app, ["new", str(root)]).exit_code == 0
    lyrics = (root / "src/lyrics.ass").read_bytes()

    result = runner.invoke(app, ["vertical-ass", "-C", str(root)])
    assert result.exit_code == 0, result.output
    script = subs.load(root / "src/vertical.ass")
    assert subs.play_res(script) == (1080, 1920)
    # .ass から見た下敷きの位置（Aegisub で開いたときに読み込まれる）
    assert script.aegisub_project["Video File"] == "../build/preview/vertical-bg.mp4"
    assert (root / "src/lyrics.ass").read_bytes() == lyrics

    # 利用者が直した縦用 .ass を作り直さない
    (root / "src/vertical.ass").write_text("編集済み", encoding="utf-8")
    again = runner.invoke(app, ["vertical-ass", "-C", str(root)])
    assert again.exit_code == 1
    assert "既にあります" in again.output
    assert (root / "src/vertical.ass").read_text(encoding="utf-8") == "編集済み"


def test_vertical_ass_for_blur_copies_the_styles_without_the_lyrics(tmp_path: Path) -> None:
    root = tmp_path / "20260916-song"
    assert runner.invoke(app, ["new", str(root)]).exit_code == 0
    with (root / "utavideo.toml").open("a", encoding="utf-8") as toml:
        toml.write('\n[vertical]\nlayout = "blur"\n')

    result = runner.invoke(app, ["vertical-ass", "-C", str(root)])
    assert result.exit_code == 0, result.output
    assert "帯に出す文字" in result.output
    script = subs.load(root / "src/vertical.ass")
    # 歌詞は本編の映像に入るので写さない。スタイルは Aegisub で選べるように写す
    assert script.events == []
    assert {"Lyrics", "Short", "VerticalBand"} <= set(script.styles)


def test_vertical_ass_needs_the_lyrics(tmp_path: Path) -> None:
    root = tmp_path / "20260916-song"
    assert runner.invoke(app, ["new", str(root)]).exit_code == 0
    (root / "src/lyrics.ass").unlink()

    result = runner.invoke(app, ["vertical-ass", "-C", str(root)])
    assert result.exit_code == 1
    assert "lyrics.file" in result.output
    assert not (root / "src/vertical.ass").exists()


def test_vertical_ass_in_another_folder_rebases_the_aegisub_paths(tmp_path: Path) -> None:
    root = tmp_path / "20260916-song"
    assert runner.invoke(app, ["new", str(root)]).exit_code == 0
    with (root / "utavideo.toml").open("a", encoding="utf-8") as toml:
        toml.write('\n[vertical]\nlyrics = "src/shorts/vertical.ass"\n')
    lyrics = root / "src/lyrics.ass"
    text = lyrics.read_text(encoding="utf-8")
    lyrics.write_text(text + "\n[Aegisub Project Garbage]\nAudio File: ../audio.wav\n", encoding="utf-8")

    result = runner.invoke(app, ["vertical-ass", "-C", str(root)])
    assert result.exit_code == 0, result.output
    project = subs.load(root / "src/shorts/vertical.ass").aegisub_project
    assert project["Audio File"] == "../../audio.wav"
    assert project["Video File"] == "../../build/preview/vertical-bg.mp4"
