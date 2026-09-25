"""曲フォルダの規約（パス・バージョン名）と、雛形からの作成。"""

import filecmp
import json
import re
import string
from collections.abc import Iterable
from dataclasses import dataclass, field
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
from utavideo.ffmpeg import write_text
from utavideo.graph import ANIMATED_EXTS, AUDIO_EXTS, IMAGE_EXTS
from utavideo.names import legacy_name_from_title, slug_error, slug_from_title
from utavideo.schema import schema_path
from utavideo.subs import escape_text

SCAFFOLD_DIRS = ("src/mix", "src/bg", "src/avatar", "src/ref", "build", "release", "share")

# 先頭に 0 の付かない整数。v1.02 を許すと v1.2 と別の音源として数えてしまう
_INT = r"(?:0|[1-9][0-9]*)"
VERSION_PATTERN = rf"v{_INT}\.{_INT}"
_VERSION_RE = re.compile(rf"(?<![0-9A-Za-z]){VERSION_PATTERN}(?![0-9A-Za-z]|\.[0-9A-Za-z])", re.IGNORECASE)
_REVISION_RE = re.compile(_INT)

# utavideo.toml に [[shorts]] が無いときに、shorts が見せる書き足し方
SHORTS_EXAMPLE = """[[shorts]]
name = "chorus"
"""

THUMBNAIL_TEMPLATE_PATH = "src/thumbnail.ass"
# utavideo.toml を書き換えない場面（既存の曲フォルダでの init、[[thumbnails]] が無いときの thumbnail）で見せる
THUMBNAIL_EXAMPLE = f"""[[thumbnails]]
name = "main"
file = "{THUMBNAIL_TEMPLATE_PATH}"
"""


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
    def inst_audio_path(self) -> Path:
        """inst（歌唱練習用の動画）に使う音源。inst.audio は audio.file とは別に必須。

        呼ぶ前に inst.audio が設定されていることを確かめておくこと
        （未設定なら analyze_inst がエラーを返し、write_video まで進まない）。
        """
        assert self.config.inst.audio is not None
        return self.resolve(self.config.inst.audio)

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
    def inputs_record(self) -> Path:
        """build/main.mp4 を書き出したときの入力の記録（release が比べる）。"""
        return self.work_dir / "main-inputs.json"

    def shorts_inputs_record(self, name: str) -> Path:
        return self.work_dir / f"shorts-{name}-inputs.json"

    def thumbnail_inputs_record(self, name: str) -> Path:
        return self.work_dir / f"thumbnail-{name}-inputs.json"

    def inst_inputs_record(self, key_label: str) -> Path:
        return self.work_dir / f"inst-key{key_label}-inputs.json"

    def release_match_record(self, suffix: str = "") -> Path:
        """release が最後に確かめた、成果物と release 済みファイルの一致の記録（issue #82）。

        main は release-match.json、ショートは release-match-shorts-<name>.json のように、
        release_path・released と同じ suffix でファイルを分ける。
        """
        return self.work_dir / f"release-match{suffix}.json"

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
    def announce_output(self) -> Path:
        return self.build_dir / "announce.txt"

    @property
    def version(self) -> str | None:
        return extract_version(self.audio_path.stem)

    @property
    def slug(self) -> str:
        """ファイル名に使う識別子。song.slug の無い曲フォルダでは曲名から作る。"""
        return self.config.song.slug or slug_from_title(self.config.song.title)

    @property
    def release_dir(self) -> Path:
        return self.root / "release"

    def release_path(self, version: str, revision: int, *, suffix: str = "") -> Path:
        return self.release_dir / f"{self.slug}{suffix}-{version}.{revision}.mp4"

    def released(self, version: str, *, suffix: str = "") -> list[tuple[int, Path]]:
        """同じ音源のバージョンで公開済みの動画を、(何本目か, パス) の一覧で返す。

        枝番を手で付けていた頃の <名前> vX.Y.mp4 は、1本目（0）とみなす（本編のみ。suffix が
        無いときだけ）。song.slug より前に公開した <曲名> vX.Y[.N].mp4 も、同じ音源のものとして数える
        （見落とすと、同じ動画が別の名前でもう一度 release されてしまう）。
        番号が同じファイルが両方あることもあるので、番号ごとに1つに絞らない。

        suffix はショートなど本編以外の成果物を release するときに使う（例: "-shorts-chorus"）。
        本編とは別の名前空間になるので、番号は suffix ごとに別々に振られる。
        """
        bases = {f"{self.slug}{suffix}-{version}"}
        if not suffix:
            bases.add(f"{legacy_name_from_title(self.config.song.title)} {version}")
        found: list[tuple[int, Path]] = []
        if not self.release_dir.is_dir():
            return found
        for path in self.release_dir.iterdir():
            if path.suffix.lower() != ".mp4" or not path.is_file():
                continue
            if path.stem in bases:
                found.append((0, path))
                continue
            for base in bases:
                rest = path.stem.removeprefix(f"{base}.")
                if rest != path.stem and _REVISION_RE.fullmatch(rest):
                    found.append((int(rest), path))
                    break
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


_RELEASE_MATCH_FORMAT = 1


def find_matching_release(
    project: Project, version: str, source: Path, *, suffix: str = ""
) -> tuple[Path | None, Path, bool]:
    """source と同じ内容の release 済みファイル、次に release したらできるファイル、release 済みの有無。

    同じ入力からの build はバイト単位で一致する（docs/verification/20260916-release-revision.md）。
    release 済みファイルは上書きしない約束なので、release が最後に確かめた一致（record_release_match）を
    source の size・mtime_ns が変わっていない間は信じ、release/ を読み直さずに済ませる（issue #82）。

    suffix は released・release_path と同じもの（本編なら省略、ショートなら "-shorts-<name>" など）を渡す。
    """
    released = project.released(version, suffix=suffix)
    matched = _cached_match(project, version, source, released, suffix=suffix)
    if matched is None:
        matched = next((path for _, path in released if filecmp.cmp(source, path, shallow=False)), None)
    return matched, project.release_path(version, next_revision(released), suffix=suffix), bool(released)


def _cached_match(
    project: Project, version: str, source: Path, released: list[tuple[int, Path]], *, suffix: str = ""
) -> Path | None:
    try:
        data = json.loads(project.release_match_record(suffix).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(data, dict)
        or data.get("format") != _RELEASE_MATCH_FORMAT
        or data.get("version") != version
    ):
        return None
    if data.get("source") != _stamp(source):
        return None
    matched_name = data.get("matched")
    return next((path for _, path in released if path.name == matched_name), None)


def record_release_match(
    project: Project, version: str, source: Path, matched: Path, *, suffix: str = ""
) -> None:
    """release が source と matched の一致を確かめたことを記録する（次回は読み直さずに済む）。"""
    data = {
        "format": _RELEASE_MATCH_FORMAT,
        "version": version,
        "source": _stamp(source),
        "matched": matched.name,
    }
    write_text(project.release_match_record(suffix), json.dumps(data, ensure_ascii=False) + "\n")


def _stamp(path: Path) -> list[int | None]:
    """大きさと更新時刻。ファイルが無ければ None の組。"""
    try:
        stat = path.stat()
    except OSError:
        return [None, None]
    return [stat.st_size, stat.st_mtime_ns]


def require_usable_slug(slug: str) -> None:
    if reason := slug_error(slug):
        raise ConfigError(f"song.slug に使えません（{reason}）: {slug!r}")


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


def scaffold(
    root: Path, title: str, slug: str, artist: str = "", defaults: Defaults | None = None
) -> ScaffoldResult:
    """雛形のディレクトリとファイルを作る。既にあるものは移動も上書きもしない。"""
    if defaults is None:
        defaults = Defaults()
    result = ScaffoldResult()
    require_usable_slug(slug)
    audio = _detect_single(root / "src", AUDIO_EXTS) or f"src/mix/{slug}-v1.0.wav"
    background = _detect_single(root / "src", IMAGE_EXTS | ANIMATED_EXTS) or "src/bg/background.png"

    for rel in SCAFFOLD_DIRS:
        directory = root / rel
        if not directory.exists():
            directory.mkdir(parents=True)
            result.created.append(directory)

    # 既にある utavideo.toml は書き換えないので、[[thumbnails]] から参照されない .ass を残さないよう作らない
    config_exists = (root / PROJECT_CONFIG_NAME).exists()
    files = {
        PROJECT_CONFIG_NAME: render_template(
            "utavideo.toml",
            schema=schema_path().as_uri(),
            title=_toml_string(title),
            slug=_toml_string(slug),
            artist=_toml_string(artist),
            audio=_toml_string(audio),
            background=_toml_string(background),
            hashtags=_toml_array(defaults.hashtags),
            announce_hashtags=_toml_array(defaults.announce_hashtags),
            credits=_toml_credits(defaults.credits),
        ),
        "src/lyrics.ass": render_template("lyrics.ass"),
        "README.md": render_template("README.md"),
    }
    if not config_exists:
        files[THUMBNAIL_TEMPLATE_PATH] = render_template(
            "thumbnail.ass", title=escape_text(title), artist=escape_text(artist)
        )
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


def render_template(name: str, **values: str) -> str:
    """templates/ のファイルの $名前 を置き換える。"""
    text = resources.files("utavideo").joinpath("templates", name).read_text(encoding="utf-8")
    return string.Template(text).substitute(values)


def read_template_bytes(*parts: str) -> bytes:
    """templates/ 配下のバイナリファイルをそのまま読む。"""
    return resources.files("utavideo").joinpath("templates", *parts).read_bytes()


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
