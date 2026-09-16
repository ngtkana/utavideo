"""曲フォルダの規約（パス・バージョン名）と、雛形からの作成。"""

import json
import re
import string
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path

from utavideo.config import (
    PROJECT_CONFIG_NAME,
    ConfigError,
    Credit,
    Defaults,
    ProjectConfig,
    load_project_config,
)
from utavideo.graph import ANIMATED_EXTS, AUDIO_EXTS, IMAGE_EXTS

SCAFFOLD_DIRS = ("src/mix", "src/bg", "src/avatar", "src/ref", "build", "release", "share")

# 先頭に 0 の付かない整数。v1.02 を許すと v1.2 と別の音源として数えてしまう
_INT = r"(?:0|[1-9][0-9]*)"
VERSION_PATTERN = rf"v{_INT}\.{_INT}"
_VERSION_RE = re.compile(rf"(?<![0-9A-Za-z]){VERSION_PATTERN}(?![0-9A-Za-z]|\.[0-9A-Za-z])", re.IGNORECASE)
_REVISION_RE = re.compile(_INT)
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
    def title_output(self) -> Path:
        return self.build_dir / "title.txt"

    @property
    def description_output(self) -> Path:
        return self.build_dir / "description.txt"

    @property
    def version(self) -> str | None:
        return extract_version(self.audio_path.stem)

    @property
    def release_dir(self) -> Path:
        return self.root / "release"

    def release_path(self, version: str, revision: int) -> Path:
        return self.release_dir / f"{safe_filename(self.config.song.title)} {version}.{revision}.mp4"

    def released(self, version: str) -> list[tuple[int, Path]]:
        """同じ音源のバージョンで公開済みの動画を、(何本目か, パス) の一覧で返す。

        枝番を手で付けていた頃の <曲名> vX.Y.mp4 は、1本目（0）とみなす。
        番号が同じファイルが両方あることもあるので、番号ごとに1つに絞らない。
        """
        base = f"{safe_filename(self.config.song.title)} {version}"
        found: list[tuple[int, Path]] = []
        if not self.release_dir.is_dir():
            return found
        for path in self.release_dir.iterdir():
            if path.suffix.lower() != ".mp4" or not path.is_file():
                continue
            rest = path.stem.removeprefix(f"{base}.")
            if path.stem == base:
                found.append((0, path))
            elif rest != path.stem and _REVISION_RE.fullmatch(rest):
                found.append((int(rest), path))
        return sorted(found)


@dataclass
class ScaffoldResult:
    created: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def extract_version(stem: str) -> str | None:
    """例: "曲名 v3.4" → "v3.4"。vX.Y の形だけを読み、複数あれば最後のもの。"""
    matches = _VERSION_RE.findall(stem)
    return matches[-1].lower() if matches else None


def next_revision(released: list[tuple[int, Path]]) -> int:
    """次に公開する動画が何本目か。数ではなく最大値から決めるので、消しても番号がぶつからない。"""
    return max((revision for revision, _ in released), default=-1) + 1


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


def scaffold(root: Path, title: str, artist: str = "", defaults: Defaults | None = None) -> ScaffoldResult:
    """雛形のディレクトリとファイルを作る。既にあるものは移動も上書きもしない。"""
    if defaults is None:
        defaults = Defaults()
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
            hashtags=_toml_array(defaults.hashtags),
            credits=_toml_credits(defaults.credits),
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


def _toml_array(values: Iterable[str]) -> str:
    return json.dumps(list(values), ensure_ascii=False)


def _toml_credits(credits: Iterable[Credit]) -> str:
    return "".join(
        f"[[credits]]\nroles = {_toml_array(c.roles)}\n"
        f"name = {_toml_string(c.name)}\nurls = {_toml_array(c.urls)}\n\n"
        for c in credits
    )
