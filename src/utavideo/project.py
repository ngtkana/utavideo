"""曲フォルダの規約（パス・バージョン名）と、雛形からの作成。"""

import json
import re
import string
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path

from utavideo.config import PROJECT_CONFIG_NAME, ConfigError, ProjectConfig, load_project_config
from utavideo.graph import ANIMATED_EXTS, AUDIO_EXTS, IMAGE_EXTS

SCAFFOLD_DIRS = ("src/mix", "src/bg", "src/avatar", "src/ref", "build", "release", "share")

_VERSION_RE = re.compile(r"(?<![0-9A-Za-z])v(\d+(?:\.\d+)*)(?![0-9A-Za-z]|\.[0-9A-Za-z])", re.IGNORECASE)
_DATE_PREFIX_RE = re.compile(r"^\d{8}[\s_-]*")
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n]')


@dataclass(frozen=True)
class Project:
    root: Path
    config: ProjectConfig

    @classmethod
    def load(cls, root: Path) -> "Project":
        return cls(root, load_project_config(root / PROJECT_CONFIG_NAME))

    def resolve(self, path: Path) -> Path:
        return path if path.is_absolute() else self.root / path

    @property
    def config_path(self) -> Path:
        return self.root / PROJECT_CONFIG_NAME

    @property
    def audio_path(self) -> Path:
        return self.resolve(self.config.audio.file)

    @property
    def background_path(self) -> Path:
        return self.resolve(self.config.video.background)

    @property
    def lyrics_path(self) -> Path:
        return self.resolve(self.config.lyrics.file)

    @property
    def build_dir(self) -> Path:
        return self.root / "build"

    @property
    def work_dir(self) -> Path:
        return self.build_dir / ".work"

    @property
    def main_output(self) -> Path:
        return self.build_dir / "main.mp4"

    @property
    def overlay_output(self) -> Path:
        return self.build_dir / "overlay.mov"

    @property
    def preview_bg_output(self) -> Path:
        return self.build_dir / "preview" / "bg.mp4"

    @property
    def version(self) -> str | None:
        return extract_version(self.audio_path.stem)

    def release_path(self, version: str) -> Path:
        return self.root / "release" / f"{safe_filename(self.config.song.title)} {version}.mp4"


@dataclass
class ScaffoldResult:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def extract_version(stem: str) -> str | None:
    """例: "曲名 v3.4" → "v3.4"。複数あれば最後のもの。"""
    matches = _VERSION_RE.findall(stem)
    return f"v{matches[-1]}" if matches else None


def safe_filename(name: str) -> str:
    """ファイル名に使えない文字を潰す。空白だけの名前は末尾が空白のフォルダ名になるので避ける。"""
    return _INVALID_FILENAME_CHARS.sub("_", name).strip() or "untitled"


def project_dir_name(title: str, day: date) -> str:
    return f"{day:%Y%m%d} {safe_filename(title)}"


def title_from_dir_name(name: str) -> str:
    """例: "20260913 新しい曲" → "新しい曲"。"""
    return _DATE_PREFIX_RE.sub("", name) or name


def find_project_root(start: Path) -> Path:
    start = start.absolute()
    for directory in (start, *start.parents):
        if (directory / PROJECT_CONFIG_NAME).is_file():
            return directory
    raise ConfigError(
        f"{PROJECT_CONFIG_NAME} が見つかりません（{start} とその親ディレクトリ）。"
        "曲フォルダで実行するか -C で指定してください。"
    )


def to_windows_path(path: Path) -> str | None:
    """WSL の /mnt/<drive>/... を Windows のパスに変換する。変換できなければ None。"""
    m = re.match(r"^/mnt/([a-zA-Z])(/.*)?$", path.absolute().as_posix())
    if m is None:
        return None
    return f"{m[1].upper()}:" + (m[2] or "/").replace("/", "\\")


def scaffold(root: Path, title: str, artist: str = "") -> ScaffoldResult:
    """雛形のディレクトリとファイルを作る。既にあるものは移動も上書きもしない。"""
    result = ScaffoldResult()
    audio = _detect_single(root / "src", AUDIO_EXTS) or f"src/mix/{safe_filename(title)} v1.0.wav"
    background = _detect_single(root / "src", IMAGE_EXTS | ANIMATED_EXTS) or "src/bg/background.png"

    for rel in SCAFFOLD_DIRS:
        directory = root / rel
        if not directory.exists():
            directory.mkdir(parents=True)
            result.created.append(directory)

    one_line_title = " ".join(title.split())
    files = {
        PROJECT_CONFIG_NAME: _render_template(
            "utavideo.toml",
            title=_toml_string(title),
            artist=_toml_string(artist),
            audio=_toml_string(audio),
            background=_toml_string(background),
        ),
        "src/lyrics.ass": _render_template("lyrics.ass", title=one_line_title),
        "README.md": _render_template("README.md", title=one_line_title),
    }
    for rel, content in files.items():
        path = root / rel
        if path.exists():
            result.skipped.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        result.created.append(path)
    return result


def _detect_single(src: Path, exts: frozenset[str]) -> str | None:
    """src/ 以下（ref/ を除く）に該当する拡張子のファイルがちょうど1つなら、曲フォルダからの相対パス。"""
    if not src.is_dir():
        return None
    candidates = [
        p
        for p in src.rglob("*")
        if p.suffix.lower() in exts and p.relative_to(src).parts[0] != "ref" and p.is_file()
    ]
    if len(candidates) != 1:
        return None
    return candidates[0].relative_to(src.parent).as_posix()


def _render_template(name: str, **values: str) -> str:
    text = resources.files("utavideo").joinpath("templates", name).read_text(encoding="utf-8")
    return string.Template(text).substitute(values)


def _toml_string(value: str) -> str:
    # JSON の文字列リテラルは TOML の basic string としても有効
    return json.dumps(value, ensure_ascii=False)
