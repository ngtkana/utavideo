"""new / init の引数と既定値、検査のメッセージ。"""

from pathlib import Path

from typer.testing import CliRunner

from utavideo.cli import _font_missing_message, app
from utavideo.config import load_project_config

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


def test_missing_font_message_points_at_the_font_name_for_a_file_name() -> None:
    message = _font_missing_message("ヒラギノ丸ゴ ProN W4.ttc", [Path("/Library/Fonts")])
    assert "ファイル名ではなくフォント名" in message
    assert "ヒラギノ丸ゴ ProN W4）" in message  # 拡張子を外した例を出す


def test_missing_font_message_tells_how_to_add_a_place_when_there_is_none() -> None:
    message = _font_missing_message("BIZ UDGothic", [])
    assert "（なし）" in message
    assert "UTAVIDEO_FONT_DIRS" in message and "font_dirs" in message


def test_missing_font_message_only_lists_the_places_when_the_name_is_plain() -> None:
    message = _font_missing_message("BIZ UDGothic", [Path("/Library/Fonts")])
    assert message == "フォント 'BIZ UDGothic' が見つかりません（探した場所: /Library/Fonts）"
