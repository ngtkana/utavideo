"""ファイル名に使う識別子（slug）の規則。"""

import re
import unicodedata
from collections.abc import Iterable

# Windows で使えない名前。拡張子を付けても使えないので、名前の先頭だけを見る
# https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"{port}{i}" for port in ("COM", "LPT") for i in range(1, 10)}
)
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_NOT_FOR_SLUG = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f\s]+')
# 日付の後ろに数字が続くものは日付ではない（123456789-song の先頭8桁など）
_DATE_PREFIX = re.compile(r"^\d{8}(?![0-9])[\s_-]*")
_LEGACY_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\r\n]')
# 拡張子とバージョン（"-v1.2.0.mp4"）を足しても、ファイル名の上限（255 バイト）に収まる長さ
MAX_SLUG_BYTES = 200


def slug_error(slug: str) -> str | None:
    """フォルダ名・ファイル名に使えない slug なら、その理由。使えるなら None。"""
    if not slug:
        return "空です"
    # ファイル名の上限はバイト数なので、文字数では数えない（日本語は1文字3バイト）
    if len(slug.encode()) > MAX_SLUG_BYTES:
        return f"長すぎます（{len(slug.encode())} バイト。{MAX_SLUG_BYTES} バイトまで）"
    if found := _INVALID_CHARS.findall(slug):
        return f"ファイル名に使えない文字が入っています: {' '.join(sorted(set(found)))}"
    if slug.startswith("-"):
        return "先頭の - は、コマンドの引数と間違われます"
    if slug != slug.rstrip(" ."):
        return "末尾の空白と点は、Windows でフォルダを開けなくします"
    if slug.split(".")[0].upper() in RESERVED_NAMES:
        return f"Windows の予約語です: {slug.split('.')[0]}"
    return None


def output_name_error(name: str) -> str | None:
    """utavideo.toml に書く出力の名前（[[thumbnails]] の name など）に使えない理由。使えるなら None。"""
    if reason := slug_error(name):
        return reason
    # <name>.partial.png は、".partial" を除いた名前の出力の書きかけ（ffmpeg.partial_path）と同じ名前になる
    if name.casefold().endswith(".partial"):
        return "末尾の .partial は、書き出し途中のファイルの名前と重なります"
    return None


def slug_from_title(title: str) -> str:
    """曲名から slug を作る。使えない文字と空白は - にする。"""
    slug = _NOT_FOR_SLUG.sub("-", unicodedata.normalize("NFC", title))
    slug = re.sub("-{2,}", "-", slug).strip("-. ")
    # 予約語のままだと Windows でフォルダを開けない。Windows は最初の . より前を見るので、
    # 末尾ではなくそこに付ける（NUL.曲 → NUL-1.曲）
    head, dot, rest = slug.partition(".")
    if head.upper() in RESERVED_NAMES:
        slug = f"{head}-1{dot}{rest}"
    # 上限はバイト数。切ったところで文字が壊れないよう、decode で落とす
    slug = slug.encode()[:MAX_SLUG_BYTES].decode(errors="ignore").strip("-. ")
    return slug or "untitled"


def slug_from_dir_name(name: str) -> str:
    """曲フォルダの名前から slug の既定値を作る。例: "20260916-新しい曲" → "新しい曲"。"""
    return _DATE_PREFIX.sub("", name) or name


def has_date_prefix(name: str) -> bool:
    """フォルダ名が YYYYMMDD で始まるか（slug を決めるときに外す部分があるか）。"""
    return slug_from_dir_name(name) != name


def legacy_name_from_title(title: str) -> str:
    """song.slug が無かった頃のファイル名。公開済みの動画を見分けるためだけに使う。"""
    return _LEGACY_INVALID_CHARS.sub("_", title).strip() or "untitled"


def casefold_duplicates(names: Iterable[str]) -> list[str]:
    """大文字小文字を区別せずに比べて、2回目以降に出てきた名前（出てきた順）。"""
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        key = name.casefold()
        if key in seen:
            duplicates.append(name)
        seen.add(key)
    return duplicates
