"""new / init の引数と既定値、サムネイルの検査、検査のメッセージ。"""

import unicodedata
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.conftest import MakeFont
from utavideo.analyze import analyze_thumbnails, font_missing_message
from utavideo.cli import app
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

    monkeypatch.setattr("utavideo.analyze.probe_duration", unreadable)
    project = Project.load(tmp_path)
    issues = analyze_thumbnails(project, project.config.thumbnails, bg_only=True).issues

    # 背景の長さの警告を重ねず、読めないエラーを1件だけ出す
    assert len(issues) == 1
    assert issues[0].level == "error" and "を読めません" in issues[0].message


def test_missing_font_message_points_at_the_font_name_for_a_file_name() -> None:
    message = font_missing_message("ヒラギノ丸ゴ ProN W4.ttc", [Path("/Library/Fonts")])
    assert "ファイル名ではなくフォント名" in message
    assert "ヒラギノ丸ゴ ProN W4）" in message  # 拡張子を外した例を出す


def test_missing_font_message_tells_how_to_add_a_place_when_there_is_none() -> None:
    message = font_missing_message("BIZ UDGothic", [])
    assert "（なし）" in message
    assert "UTAVIDEO_FONT_DIRS" in message and "font_dirs" in message


def test_missing_font_message_only_lists_the_places_when_the_name_is_plain() -> None:
    message = font_missing_message("BIZ UDGothic", [Path("/Library/Fonts")])
    assert message == "フォント 'BIZ UDGothic' が見つかりません（探した場所: /Library/Fonts）"


def test_fonts_lists_files_and_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_font: MakeFont
) -> None:
    font = make_font(tmp_path / "fonts" / "Test.ttf", "テストゴシック")
    monkeypatch.setenv("UTAVIDEO_FONT_DIRS", str(tmp_path / "fonts"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    result = runner.invoke(app, ["fonts"])

    assert result.exit_code == 0, result.output
    assert str(tmp_path / "fonts") in result.output
    assert f"{font} | テストゴシック" in result.output


def test_fonts_with_a_name_prints_only_the_matching_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_font: MakeFont
) -> None:
    font = make_font(tmp_path / "fonts" / "Test.ttf", "テストゴシック")
    monkeypatch.setenv("UTAVIDEO_FONT_DIRS", str(tmp_path / "fonts"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    result = runner.invoke(app, ["fonts", "テストゴシック"])

    assert result.exit_code == 0, result.output
    # 進捗は stderr に出すので、stdout（スクリプトが受け取る側）にはパスだけが並ぶ
    assert result.stdout == f"{font}\n"


def test_fonts_with_a_name_lists_each_file_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_font: MakeFont
) -> None:
    # フォントの name テーブルに同じ名前の NFC・NFD 表記が両方入っていても、
    # 同じファイルを重ねて出さない（match_key が同じになるため）
    nfc = unicodedata.normalize("NFC", "テストゴシック")
    nfd = unicodedata.normalize("NFD", nfc)
    font = make_font(tmp_path / "fonts" / "Test.ttf", nfc)
    monkeypatch.setattr("utavideo.fonts.read_font_names", lambda path: {nfc, nfd} if path == font else set())
    monkeypatch.setenv("UTAVIDEO_FONT_DIRS", str(tmp_path / "fonts"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    result = runner.invoke(app, ["fonts", nfc])

    assert result.exit_code == 0, result.output
    assert result.stdout == f"{font}\n"


def test_fonts_with_an_unknown_name_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UTAVIDEO_FONT_DIRS", str(tmp_path / "fonts"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    result = runner.invoke(app, ["fonts", "無い書体"])

    assert result.exit_code == 1
    assert "見つかりません" in result.output
