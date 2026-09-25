"""utavideo.toml（曲ごとの設定）とユーザー設定の読み込み。"""

import glob
import os
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    ValidationError,
    WithJsonSchema,
    field_validator,
)
from pydantic_core import to_jsonable_python

from utavideo.errors import UtavideoError
from utavideo.graph import Fit, Preset, ScaleFlags
from utavideo.names import casefold_duplicates, output_name_error, slug_error
from utavideo.timecode import parse_time

PROJECT_CONFIG_NAME = "utavideo.toml"


class ConfigError(UtavideoError):
    """設定ファイルが読めない、または内容が不正。"""


def format_setting(template: str, setting: str, **values: str) -> str:
    """設定に書かれた {名前} を置き換える。"""
    try:
        return template.format(**values)
    # {section.foo} は AttributeError、{section[a]} は TypeError になる
    except (KeyError, IndexError, ValueError, AttributeError, TypeError) as e:
        names = ", ".join(values)
        raise ConfigError(f"{setting} の書式が不正です（使える名前は {names}）: {e}") from e


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# 背景を出力の枠に合わせるときの基準点。0〜1 の比率（CSS の object-position と同じ考え方）。
# strict にして、TOML の true を 1 として読まないようにする
Ratio = Annotated[float, Field(ge=0, le=1, strict=True)]
type Focus = tuple[Ratio, Ratio]

# フェードの長さ（イン, アウト）。ミリ秒
type FadeMs = tuple[NonNegativeInt, NonNegativeInt]

# "M:SS(.fff)" または秒の数。読むときに秒（float）にする。
# BeforeValidator は入力の型を JSON Schema に伝えないので、WithJsonSchema で文字列も許すと明記する
# （無いと taplo が "1:23.5" のような文字列を型不一致として警告してしまう）
Time = Annotated[
    float, BeforeValidator(parse_time), WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "number"}]})
]


def _check_output_name(name: str) -> str:
    # 黙って直すと、指定した名前と違うファイルができるのでエラーにする
    if reason := output_name_error(name):
        raise ValueError(reason)
    return name


# 出力のファイル名になる名前（[[thumbnails]] の name など）
OutputName = Annotated[str, AfterValidator(_check_output_name)]


def check_unique_names[T](items: tuple[T, ...], name_of: Callable[[T], str]) -> tuple[T, ...]:
    """名前の重複をエラーにする。

    Windows のファイルシステムでは、大文字小文字が違うだけの名前は同じファイルになる。
    """
    if duplicates := casefold_duplicates(name_of(item) for item in items):
        raise ValueError(f"name が重複しています（大文字小文字は区別しません）: {', '.join(duplicates)}")
    return items


class _NotRendered:
    """動画の描画に効かない項目の印。Annotated[型, NOT_RENDERED] と書く。

    release は、印の無い項目がすべて描画に効くとみなして build のときの値と比べる。
    印を付け忘れても release が余計に止まるだけで、確かめていない動画は公開されない。
    """

    def __repr__(self) -> str:
        return "NOT_RENDERED"


NOT_RENDERED = _NotRendered()


def rendered_values(value: object) -> object:
    """設定の値から NOT_RENDERED の項目を除き、JSON にできる形にする。"""
    if isinstance(value, BaseModel):
        return {
            name: rendered_values(getattr(value, name))
            for name, info in type(value).model_fields.items()
            if NOT_RENDERED not in info.metadata
        }
    if isinstance(value, tuple):
        return [rendered_values(item) for item in value]
    return to_jsonable_python(value)


class Song(_Model):
    title: str
    # 空なら title から作る（この項目より前に作った曲フォルダとの互換）
    slug: Annotated[str, NOT_RENDERED] = ""
    artist: str = ""
    label: str = ""
    original_urls: Annotated[tuple[str, ...], NOT_RENDERED] = ()

    @field_validator("slug")
    @classmethod
    def _usable_as_a_name(cls, slug: str) -> str:
        # 黙って直すと、指定した名前と違うファイルができるのでエラーにする
        if slug and (reason := slug_error(slug)):
            raise ValueError(reason)
        return slug


class Audio(_Model):
    file: Path


def _check_even_size(size: tuple[int, int]) -> tuple[int, int]:
    if size[0] % 2 or size[1] % 2:
        raise ValueError("幅と高さは偶数にしてください（yuv420p の制約）")
    return size


# 動画の解像度。yuv420p で書き出すので偶数
VideoSize = Annotated[tuple[PositiveInt, PositiveInt], AfterValidator(_check_even_size)]


class Video(_Model):
    background: Path
    size: VideoSize = (1920, 1080)
    fps: PositiveInt = 30
    crf: int = Field(default=18, ge=0, le=51)
    preset: Preset = "slow"
    fit: Fit = "cover"
    focus: Focus = (0.5, 0.5)
    scale_flags: ScaleFlags = "lanczos"
    pad_color: str = "black"


class Lyrics(_Model):
    file: Path = Path("src/lyrics.ass")
    fade_ms: FadeMs = (150, 150)


class OverlayText(_Model):
    enabled: bool = True
    style: str = "Title"
    text: str = "{title} / {artist}"


class Credit(_Model):
    roles: tuple[str, ...] = Field(min_length=1)
    name: str
    urls: tuple[str, ...] = ()


class Material(_Model):
    section: str
    urls: tuple[str, ...] = ()
    files: tuple[Path, ...] = ()


def _check_hashtags(tags: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    for tag in tags:
        if not tag or tag.startswith("#") or any(ch.isspace() for ch in tag):
            raise ValueError(f"ハッシュタグは # と空白を付けずに書いてください: {tag!r}")
        # YouTube も X も大文字と小文字を区別しないので、違いがそれだけなら同じタグ
        if (key := tag.casefold()) in seen:
            raise ValueError(f"ハッシュタグが重複しています: {tag!r}")
        seen.add(key)
    return tags


Hashtags = Annotated[tuple[str, ...], AfterValidator(_check_hashtags)]


class Description(_Model):
    text: str = ""
    hashtags: Hashtags = ()
    title: str | None = None


class Thumbnail(_Model):
    name: OutputName
    file: Path
    # 動画と違い yuv420p にしないので、奇数でもよい
    size: tuple[PositiveInt, PositiveInt] | None = None  # None なら video.size
    # 0 と区別するのは、画像の背景に書いたことをエラーにするため
    at: Time | None = None
    focus: Focus | None = None  # None なら video.focus


class Vertical(_Model):
    """縦型のショートの共通設定。"""

    size: VideoSize = (1080, 1920)
    lyrics: Path = Path("src/vertical.ass")
    focus: Focus | None = None  # None なら video.focus
    overlay_text: bool = True  # false なら、縦だけ曲名表示（[overlay_text]）を出さない
    audio_fade_ms: FadeMs = (300, 1000)  # 区間の端の音声のフェード。wide の版にも効く


class Short(_Model):
    """縦型のショート1本。区間は縦用 .ass の、本文が name のコメント行（スタイル Short）に置く。"""

    name: OutputName
    focus: Focus | None = None  # None なら vertical.focus
    wide: bool = False  # 同じ区間の 16:9 版（build/shorts/wide/<name>.mp4）も書き出す


class Upload(_Model):
    url: str


class Announce(_Model):
    text: str = ""
    hashtags: Hashtags = ()


class Inst(_Model):
    """歌唱練習用の動画（inst）に描く、曲名・キーの表示と、使う音源。"""

    text: str = "{title} / {artist}（Key: {key}）"
    audio: Path | None = None


class ProjectConfig(_Model):
    song: Song
    audio: Audio
    video: Video
    lyrics: Lyrics = Field(default_factory=Lyrics)
    overlay_text: OverlayText = Field(default_factory=OverlayText)
    credits: Annotated[tuple[Credit, ...], NOT_RENDERED] = ()
    materials: Annotated[tuple[Material, ...], NOT_RENDERED] = ()
    description: Annotated[Description | None, NOT_RENDERED] = None
    thumbnails: Annotated[tuple[Thumbnail, ...], NOT_RENDERED] = ()
    vertical: Annotated[Vertical, NOT_RENDERED] = Field(default_factory=Vertical)
    shorts: Annotated[tuple[Short, ...], NOT_RENDERED] = ()
    uploads: Annotated[tuple[Upload, ...], NOT_RENDERED] = ()
    announce: Annotated[Announce | None, NOT_RENDERED] = None
    inst: Annotated[Inst, NOT_RENDERED] = Field(default_factory=Inst)

    @field_validator("thumbnails")
    @classmethod
    def _unique_thumbnail_names(cls, thumbnails: tuple[Thumbnail, ...]) -> tuple[Thumbnail, ...]:
        return check_unique_names(thumbnails, lambda t: t.name)

    @field_validator("shorts")
    @classmethod
    def _unique_short_names(cls, shorts: tuple[Short, ...]) -> tuple[Short, ...]:
        return check_unique_names(shorts, lambda s: s.name)


def _xdg(var: str, fallback: str) -> Path:
    """XDG の基準ディレクトリ。環境変数が無ければホームディレクトリ下の既定値。"""
    return Path(os.environ.get(var) or Path.home() / fallback)


def _font_dir_candidates() -> list[Path]:
    """OS ごとのシステム・ユーザーフォントの場所（存在しないものも含む）。"""
    if sys.platform == "win32":
        dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        if local := os.environ.get("LOCALAPPDATA"):
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        return dirs
    if sys.platform == "darwin":
        # /Network/Library/Fonts は、マウントされていないと存在を調べるだけで待たされるので入れない。
        # Supplemental などのサブディレクトリは、探すときに再帰的にたどる。
        dirs = [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library/Fonts",
        ]
    else:
        dirs = [Path("/mnt/c/Windows/Fonts")]
        dirs += sorted(map(Path, glob.glob("/mnt/c/Users/*/AppData/Local/Microsoft/Windows/Fonts")))
    # fontconfig（/etc/fonts/fonts.conf）が既定で見る 4 か所。POSIX（macOS を含む）で共通に見る。
    # Homebrew や、Linux から dotfiles ごと持ってきた macOS 利用者のためにも残す
    dirs += [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        _xdg("XDG_DATA_HOME", ".local/share") / "fonts",
        Path.home() / ".fonts",
    ]
    return dirs


def default_font_dirs() -> list[Path]:
    return [d for d in _font_dir_candidates() if d.is_dir()]


type Block = Literal["text", "original", "credits", "materials", "hashtags"]


class DescriptionFormat(_Model):
    title: str = "{title} / {artist}（Cover: {singers}）"
    singer_roles: tuple[str, ...] = ("Vocal",)
    singer_separator: str = ", "
    heading: str = "■{section}"
    original_heading: str = "原曲"
    role_separator: str = ", "
    name_url_separator: str = " "
    section_gap: NonNegativeInt = 0
    hashtags_gap: NonNegativeInt = 1
    order: tuple[Block, ...] = ("text", "original", "credits", "materials", "hashtags")

    @field_validator("order")
    @classmethod
    def _unique_blocks(cls, order: tuple[Block, ...]) -> tuple[Block, ...]:
        if len(set(order)) != len(order):
            raise ValueError("同じブロックを2回書かないでください")
        return order


type Site = Literal["youtube", "niconico"]
SITE_NAMES: dict[Site, str] = {"youtube": "YouTube", "niconico": "ニコニコ動画"}
type AnnounceBlock = Literal["header", "text", "work", "links", "hashtags", ""]


class AnnounceFormat(_Model):
    header: str = "【動画投稿】"
    work: str = "『{title} / {artist}』"
    link: str = "{site} » {url}"
    # 書いた順にリンクを並べる（tomllib も pydantic の dict も順番を保つ）
    sites: dict[Site, str] = Field(default_factory=lambda: dict(SITE_NAMES))
    order: tuple[AnnounceBlock, ...] = ("header", "text", "", "work", "", "links", "", "hashtags")
    max_weight: PositiveInt = 280

    @field_validator("order")
    @classmethod
    def _unique_blocks(cls, order: tuple[AnnounceBlock, ...]) -> tuple[AnnounceBlock, ...]:
        blocks = [block for block in order if block]  # 空行（""）は何度書いてもよい
        if len(set(blocks)) != len(blocks):
            raise ValueError('同じブロックを2回書かないでください（空行の "" は除く）')
        return order


class Defaults(_Model):
    credits: tuple[Credit, ...] = ()
    hashtags: Hashtags = ()
    announce_hashtags: Hashtags = ()


class UserConfig(_Model):
    font_dirs: list[Path] = Field(default_factory=default_font_dirs)
    description: DescriptionFormat = Field(default_factory=DescriptionFormat)
    announce: AnnounceFormat = Field(default_factory=AnnounceFormat)
    defaults: Defaults = Field(default_factory=Defaults)

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
