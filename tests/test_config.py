import sys
from pathlib import Path

import pytest

from utavideo.config import (
    ConfigError,
    _font_dir_candidates,
    load_project_config,
    load_user_config,
)

MINIMAL = """
[song]
title = "曲"
[audio]
file = "src/mix/曲 v1.0.wav"
[video]
background = "src/bg/bg.png"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "utavideo.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_minimal_config_uses_defaults(tmp_path: Path) -> None:
    config = load_project_config(_write(tmp_path, MINIMAL))
    assert config.video.size == (1920, 1080)
    assert config.video.fps == 30
    assert config.lyrics.file == Path("src/lyrics.ass")
    assert config.lyrics.fade_ms == (150, 150)
    assert config.overlay_text.style == "Title"


def test_unknown_key_is_reported_with_location(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"video\.bakground"):
        load_project_config(_write(tmp_path, MINIMAL + 'bakground = "typo.png"\n'))


def test_odd_size_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="偶数"):
        load_project_config(_write(tmp_path, MINIMAL + "size = [1921, 1080]\n"))


def test_negative_fade_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="fade_ms"):
        load_project_config(_write(tmp_path, MINIMAL + "[lyrics]\nfade_ms = [-500, 150]\n"))


def test_unknown_preset_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="preset"):
        load_project_config(_write(tmp_path, MINIMAL + 'preset = "ultrafst"\n'))


def test_broken_toml_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="TOML"):
        load_project_config(_write(tmp_path, "[song\n"))


def test_user_config_file_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("UTAVIDEO_FONT_DIRS", raising=False)
    (tmp_path / "utavideo").mkdir()
    (tmp_path / "utavideo/config.toml").write_text('font_dirs = ["/fonts/a"]\n', encoding="utf-8")
    assert load_user_config().font_dirs == [Path("/fonts/a")]

    monkeypatch.setenv("UTAVIDEO_FONT_DIRS", "/fonts/b:/fonts/c")
    assert load_user_config().font_dirs == [Path("/fonts/b"), Path("/fonts/c")]


def test_font_dirs_expand_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("UTAVIDEO_FONT_DIRS", raising=False)
    (tmp_path / "config/utavideo").mkdir(parents=True)
    (tmp_path / "config/utavideo/config.toml").write_text('font_dirs = ["~/fonts"]\n', encoding="utf-8")
    assert load_user_config().font_dirs == [home / "fonts"]

    monkeypatch.setenv("UTAVIDEO_FONT_DIRS", "~/other")
    assert load_user_config().font_dirs == [home / "other"]


@pytest.mark.skipif(sys.platform == "win32", reason="fontconfig の既定値は POSIX のもの")
def test_font_dir_candidates_cover_fontconfig_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    candidates = _font_dir_candidates()
    for expected in [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        tmp_path / "xdg/fonts",
        tmp_path / ".fonts",
    ]:
        assert expected in candidates


def test_hashtags_are_written_without_hash(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"description\.hashtags"):
        load_project_config(_write(tmp_path, MINIMAL + '[description]\nhashtags = ["#歌ってみた"]\n'))


THUMBNAILS = """
[[thumbnails]]
name = "main"
file = "src/thumbnail.ass"
"""


def test_focus_defaults_to_center_and_thumbnails_inherit_video(tmp_path: Path) -> None:
    config = load_project_config(_write(tmp_path, MINIMAL + THUMBNAILS))
    assert config.video.focus == (0.5, 0.5)
    (thumbnail,) = config.thumbnails
    assert (thumbnail.size, thumbnail.at, thumbnail.focus) == (None, None, None)


def test_config_without_thumbnails_still_loads(tmp_path: Path) -> None:
    assert load_project_config(_write(tmp_path, MINIMAL)).thumbnails == ()


def test_thumbnail_fields(tmp_path: Path) -> None:
    text = (
        MINIMAL.replace("[video]\n", "[video]\nfocus = [1, 0]\n")
        + THUMBNAILS
        + (
            'at = "1:23.5"\nsize = [1081, 1081]\nfocus = [0.25, 1.0]\n'
            '[[thumbnails]]\nname = "square"\nfile = "a.ass"\nat = 2\n'
        )
    )
    config = load_project_config(_write(tmp_path, text))
    assert config.video.focus == (1.0, 0.0)
    main, square = config.thumbnails
    assert (main.at, main.size, main.focus) == (83.5, (1081, 1081), (0.25, 1.0))  # 奇数でもよい
    assert square.at == 2.0


@pytest.mark.parametrize(
    ("extra", "location"),
    [
        ("focus = [1.5, 0.5]", "video.focus"),
        ("focus = [-0.1, 0.5]", "video.focus"),
        ("focus = [true, 0.5]", "video.focus"),
        ("focus = [0.5]", "video.focus"),
        ('focus = ["0.5", 0.5]', "video.focus"),
    ],
)
def test_focus_is_validated(tmp_path: Path, extra: str, location: str) -> None:
    with pytest.raises(ConfigError, match=location.replace(".", r"\.")):
        load_project_config(_write(tmp_path, MINIMAL + extra + "\n"))


@pytest.mark.parametrize(
    ("thumbnail", "message"),
    [
        ('at = "83.5"', "M:SS"),
        ("at = -1", "0 以上"),
        ('name = "CON"', "予約語"),
        ('name = "a/b"', "使えない文字"),
        ('name = "main.partial"', "partial"),
        ("focus = [2, 0]", r"thumbnails\.0\.focus"),
        ("size = [0, 100]", r"thumbnails\.0\.size"),
    ],
)
def test_thumbnail_values_are_validated(tmp_path: Path, thumbnail: str, message: str) -> None:
    key = thumbnail.split(" ")[0]
    lines = [line for line in THUMBNAILS.strip().splitlines() if not line.startswith(f"{key} ")]
    with pytest.raises(ConfigError, match=message):
        load_project_config(_write(tmp_path, MINIMAL + "\n".join([*lines, thumbnail]) + "\n"))


def test_thumbnail_names_must_differ_ignoring_case(tmp_path: Path) -> None:
    text = MINIMAL + THUMBNAILS + THUMBNAILS.replace('"main"', '"Main"')
    with pytest.raises(ConfigError, match=r"重複.*Main"):
        load_project_config(_write(tmp_path, text))
