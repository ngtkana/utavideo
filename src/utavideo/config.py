"""utavideo.toml（曲ごとの設定）とユーザー設定の読み込み。"""

import glob
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    ValidationError,
    field_validator,
)

from utavideo.errors import UtavideoError
from utavideo.graph import Fit, Preset, ScaleFlags

PROJECT_CONFIG_NAME = "utavideo.toml"


class ConfigError(UtavideoError):
    """設定ファイルが読めない、または内容が不正。"""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Song(_Model):
    title: str
    artist: str = ""
    label: str = ""


class Audio(_Model):
    file: Path


class Video(_Model):
    background: Path
    size: tuple[PositiveInt, PositiveInt] = (1920, 1080)
    fps: PositiveInt = 30
    crf: int = Field(default=18, ge=0, le=51)
    preset: Preset = "slow"
    fit: Fit = "cover"
    scale_flags: ScaleFlags = "lanczos"
    pad_color: str = "black"

    @field_validator("size")
    @classmethod
    def _even_size(cls, size: tuple[int, int]) -> tuple[int, int]:
        if size[0] % 2 or size[1] % 2:
            raise ValueError("幅と高さは偶数にしてください（yuv420p の制約）")
        return size


class Lyrics(_Model):
    file: Path = Path("src/lyrics.ass")
    fade_ms: tuple[NonNegativeInt, NonNegativeInt] = (150, 150)


class OverlayText(_Model):
    enabled: bool = True
    style: str = "Title"
    text: str = "{title} / {artist}"


class ProjectConfig(_Model):
    song: Song
    audio: Audio
    video: Video
    lyrics: Lyrics = Field(default_factory=Lyrics)
    overlay_text: OverlayText = Field(default_factory=OverlayText)


def _xdg(var: str, fallback: str) -> Path:
    """XDG の基準ディレクトリ。環境変数が無ければホームディレクトリ下の既定値。"""
    return Path(os.environ.get(var) or Path.home() / fallback)


def _font_dir_candidates() -> list[Path]:
    """Windows 側のシステム・ユーザーフォントと、Linux 側のフォントの場所（存在しないものも含む）。"""
    if sys.platform == "win32":
        dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        if local := os.environ.get("LOCALAPPDATA"):
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        return dirs
    dirs = [Path("/mnt/c/Windows/Fonts")]
    dirs += sorted(map(Path, glob.glob("/mnt/c/Users/*/AppData/Local/Microsoft/Windows/Fonts")))
    # fontconfig（/etc/fonts/fonts.conf）が既定で見る 4 か所
    dirs += [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        _xdg("XDG_DATA_HOME", ".local/share") / "fonts",
        Path.home() / ".fonts",
    ]
    return dirs


def default_font_dirs() -> list[Path]:
    return [d for d in _font_dir_candidates() if d.is_dir()]


class UserConfig(_Model):
    font_dirs: list[Path] = Field(default_factory=default_font_dirs)

    @field_validator("font_dirs")
    @classmethod
    def _absolute(cls, dirs: list[Path]) -> list[Path]:
        # フォント一覧のキャッシュはパス文字列をキーにするので、絶対パスに揃える
        return [d.expanduser().absolute() for d in dirs]


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "utavideo"


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / "utavideo"


def load_project_config(path: Path) -> ProjectConfig:
    return _validate(ProjectConfig, _read_toml(path), path)


def load_user_config() -> UserConfig:
    """~/.config/utavideo/config.toml を読む。環境変数 UTAVIDEO_FONT_DIRS があれば優先する。"""
    path = config_dir() / "config.toml"
    data = _read_toml(path) if path.is_file() else {}
    if env := os.environ.get("UTAVIDEO_FONT_DIRS"):
        data = {**data, "font_dirs": [p for p in env.split(os.pathsep) if p]}
    return _validate(UserConfig, data, path)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"{path} を読めません: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} の TOML 構文が不正です: {e}") from e


def _validate[M: BaseModel](model: type[M], data: dict[str, Any], path: Path) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        lines = [f"  {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]
        raise ConfigError(f"{path} の内容が不正です:\n" + "\n".join(lines)) from e
