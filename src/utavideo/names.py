"""ファイル名に使う識別子（slug）の規則。"""

import re
import unicodedata

# Windows で使えない名前。拡張子を付けても使えないので、名前の先頭だけを見る
# https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"{port}{i}" for port in ("COM", "LPT") for i in range(1, 10)}
)
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_NOT_FOR_SLUG = re.compile(r'[\\/:*?"<>|\x00-\x1f\s]+')
_DATE_PREFIX = re.compile(r"^\d{8}[\s_-]*")
# 拡張子とバージョン（"-v1.2.mp4"）を足しても、ファイルシステムの上限（255）に収まる長さ
MAX_SLUG_LEN = 200


def slug_error(slug: str) -> str | None:
    """フォルダ名・ファイル名に使えない slug なら、その理由。使えるなら None。"""
    if not slug:
        return "空です"
    if len(slug) > MAX_SLUG_LEN:
        return f"長すぎます（{len(slug)} 文字。{MAX_SLUG_LEN} 文字まで）"
    if found := _INVALID_CHARS.findall(slug):
        return f"ファイル名に使えない文字が入っています: {' '.join(sorted(set(found)))}"
    if slug != slug.rstrip(" ."):
        return "末尾の空白と点は、Windows でフォルダを開けなくします"
    if slug.split(".")[0].upper() in RESERVED_NAMES:
        return f"Windows の予約語です: {slug.split('.')[0]}"
    return None


def slug_from_title(title: str) -> str:
    """曲名から slug を作る。使えない文字と空白は - にする。"""
    slug = _NOT_FOR_SLUG.sub("-", unicodedata.normalize("NFC", title))
    slug = re.sub("-{2,}", "-", slug).strip("-. ")[:MAX_SLUG_LEN].strip("-. ")
    if not slug:
        return "untitled"
    # 予約語のままだと Windows でフォルダを開けない
    return f"{slug}-1" if slug.split(".")[0].upper() in RESERVED_NAMES else slug


def slug_from_dir_name(name: str) -> str:
    """曲フォルダの名前から slug の既定値を作る。例: "20260916-新しい曲" → "新しい曲"。"""
    return _DATE_PREFIX.sub("", name) or name
