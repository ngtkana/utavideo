from pathlib import Path

import pytest

from utavideo.config import ConfigError, load_project_config, load_user_config

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
