from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from utavideo import description
from utavideo.cli import app
from utavideo.config import ConfigError, DescriptionFormat, ProjectConfig, load_project_config
from utavideo.project import Project

runner = CliRunner()

SONG: dict[str, Any] = {
    "song": {"title": "曲", "artist": "作者", "original_urls": ["https://example.com/original"]},
    "audio": {"file": "src/mix/曲 v1.0.wav"},
    "video": {"background": "src/bg/bg.png"},
    "credits": [
        {"roles": ["Vocal", "Mix"], "name": "歌う人", "urls": ["https://example.com/singer"]},
        {"roles": ["Vocal"], "name": "ゲスト"},
        {"roles": ["Vocal", "Mix"], "name": "もう一人"},
    ],
    "materials": [
        {"section": "イラスト", "urls": ["https://example.com/illust"], "files": ["src/bg/bg.png"]},
        {"section": "自作", "files": ["src/bg/own.png"]},
        {"section": "イラスト", "urls": ["https://example.com/illust2"]},
    ],
    "description": {"text": "\n冒頭の文章。\n\n", "hashtags": ["歌ってみた", "cover"]},
}


def _config(**overrides: Any) -> ProjectConfig:
    return ProjectConfig.model_validate({**SONG, **overrides})


def test_body_groups_people_by_roles_and_materials_by_section() -> None:
    assert description.render_body(_config(), DescriptionFormat()) == (
        "冒頭の文章。\n"
        "\n"
        "■原曲\nhttps://example.com/original\n"
        "■Vocal, Mix\n歌う人 https://example.com/singer\nもう一人\n"
        "■Vocal\nゲスト\n"
        "■イラスト\nhttps://example.com/illust\nhttps://example.com/illust2\n"
        "\n"
        "#歌ってみた #cover\n"
    )


def test_body_format_is_configurable() -> None:
    fmt = DescriptionFormat(
        heading="❖ {section}",
        original_heading="本家動画様",
        name_url_separator="\n",
        section_gap=1,
        hashtags_gap=0,
    )
    assert description.render_body(_config(), fmt) == (
        "冒頭の文章。\n"
        "\n"
        "❖ 本家動画様\nhttps://example.com/original\n"
        "\n"
        "❖ Vocal, Mix\n歌う人\nhttps://example.com/singer\nもう一人\n"
        "\n"
        "❖ Vocal\nゲスト\n"
        "\n"
        "❖ イラスト\nhttps://example.com/illust\nhttps://example.com/illust2\n"
        "#歌ってみた #cover\n"
    )


def test_body_follows_order_and_skips_empty_blocks() -> None:
    config = _config(credits=[], materials=[], song={"title": "曲"})
    fmt = DescriptionFormat(order=("hashtags", "credits", "text"))
    assert description.render_body(config, fmt) == "#歌ってみた #cover\n\n冒頭の文章。\n"
    assert (
        description.render_body(
            _config(description=None, credits=[], materials=[], song={"title": "曲"}), fmt
        )
        == ""
    )


def test_title_lists_singers_unless_overridden() -> None:
    assert (
        description.render_title(_config(), DescriptionFormat())
        == "曲 / 作者（Cover: 歌う人, ゲスト, もう一人）"
    )
    fmt = DescriptionFormat(
        title="{title}/{artist}（Cover: {singers}）", singer_roles=("Mix",), singer_separator="、"
    )
    assert description.render_title(_config(), fmt) == "曲/作者（Cover: 歌う人、もう一人）"
    overridden = _config(description={"title": "手で書いたタイトル"})
    assert description.render_title(overridden, fmt) == "手で書いたタイトル"


def test_unknown_name_in_format_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="title, artist, label, singers"):
        description.render_title(_config(), DescriptionFormat(title="{composer}"))


def test_order_rejects_duplicates() -> None:
    with pytest.raises(ValidationError, match="2回"):
        DescriptionFormat.model_validate({"order": ["text", "text"]})


def _project(tmp_path: Path, **overrides: Any) -> Project:
    (tmp_path / "src/bg").mkdir(parents=True)
    (tmp_path / "src/bg/bg.png").write_bytes(b"png")
    return Project(tmp_path, _config(**overrides))


def test_lint_passes_when_everything_is_credited(tmp_path: Path) -> None:
    project = _project(
        tmp_path, materials=[{"section": "イラスト", "urls": ["u"], "files": ["./src/bg/bg.png"]}]
    )
    assert description.lint(project, DescriptionFormat()) == []


def test_lint_warns_uncredited_background_missing_files_and_no_singers(tmp_path: Path) -> None:
    project = _project(tmp_path, credits=[], materials=[{"section": "自作", "files": ["src/bg/none.png"]}])
    messages = [issue.message for issue in description.lint(project, DescriptionFormat())]
    assert len(messages) == 3
    assert "materials.files のファイルがありません" in messages[0]
    assert "video.background" in messages[1]
    assert "{singers}" in messages[2]


def test_lint_warns_youtube_limits(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        materials=[{"section": "イラスト", "files": ["src/bg/bg.png"]}],
        description={"title": "x" * 101, "text": "<" + "あ" * 1700},
    )
    levels_and_messages = [(i.level, i.message) for i in description.lint(project, DescriptionFormat())]
    assert [level for level, _ in levels_and_messages] == ["warning"] * 3
    assert "101 文字" in levels_and_messages[0][1]
    assert "バイト" in levels_and_messages[1][1]
    assert "<" in levels_and_messages[2][1]


def test_lint_reports_broken_format_as_error(tmp_path: Path) -> None:
    project = _project(tmp_path)
    [issue] = description.lint(project, DescriptionFormat(heading="■{sectoin}"))
    assert issue.level == "error"
    assert "description.heading" in issue.message


def test_description_command_and_release_use_user_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    user_config = tmp_path / "config/utavideo/config.toml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        '[description]\ntitle = "{title}"\n\n'
        '[defaults]\nhashtags = ["歌ってみた"]\n[[defaults.credits]]\nroles = ["Vocal"]\nname = "歌う人"\n',
        encoding="utf-8",
    )
    assert runner.invoke(app, ["new", "曲", "--root", str(tmp_path), "--date", "20260916"]).exit_code == 0
    root = tmp_path / "20260916 曲"
    assert load_project_config(root / "utavideo.toml").credits[0].name == "歌う人"

    result = runner.invoke(app, ["description", "-C", str(root)])
    assert result.exit_code == 0, result.output
    body = "■Vocal\n歌う人\n\n#歌ってみた\n"
    assert (root / "build/title.txt").read_text(encoding="utf-8") == "曲"
    assert (root / "build/description.txt").read_text(encoding="utf-8") == body

    (root / "build/main.mp4").write_bytes(b"mp4")
    result = runner.invoke(app, ["release", "-C", str(root)])
    assert result.exit_code == 0, result.output
    assert (root / "release/曲 v1.0.txt").read_text(encoding="utf-8") == "曲\n\n" + body
