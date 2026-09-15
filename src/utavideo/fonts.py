"""字幕が使うフォントを探し、libass に渡す fontsdir を用意する。

libass は WSL 側の fontconfig しか見ないため、Windows 側のフォントは fontsdir で渡す必要がある。
フォントディレクトリを丸ごと渡すと libass が毎回全ファイルを読み込んで遅いので、
必要なファイルだけへのシンボリックリンクを集めたディレクトリを作って渡す。
"""

import hashlib
import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

FONT_EXTS = frozenset({".ttf", ".otf", ".ttc", ".otc"})
# libass が照合する名前: family, full name, PostScript name, typographic family
_NAME_IDS = frozenset({1, 4, 6, 16})
_CACHE_FORMAT = 1


@dataclass(frozen=True)
class FontIndex:
    files_by_name: dict[str, tuple[Path, ...]]

    def lookup(self, name: str) -> tuple[Path, ...]:
        return self.files_by_name.get(name.casefold(), ())


@dataclass(frozen=True)
class FontResolution:
    files: tuple[Path, ...]
    missing: tuple[str, ...]


def read_font_names(path: Path) -> set[str]:
    """フォントファイルに含まれる名前（全言語）。読めないファイルは空集合。"""
    names: set[str] = set()
    try:
        if path.suffix.lower() in {".ttc", ".otc"}:
            collection = TTCollection(path, lazy=True)
            fonts = list(collection.fonts)
        else:
            collection = None
            fonts = [TTFont(path, lazy=True)]
        try:
            for font in fonts:
                if "name" not in font:
                    continue
                for record in font["name"].names:
                    if record.nameID in _NAME_IDS:
                        text = record.toUnicode(errors="ignore").strip()
                        if text:
                            names.add(text)
        finally:
            for font in fonts:
                font.close()
            if collection is not None:
                collection.close()
    except Exception:  # 壊れた・未対応のフォントは候補から外すだけ
        return set()
    return names


def iter_font_files(dirs: Iterable[Path]) -> Iterator[Path]:
    for directory in dirs:
        if directory.is_dir():
            for path in sorted(directory.rglob("*")):
                if path.suffix.lower() in FONT_EXTS and path.is_file():
                    yield path


def load_index(dirs: Iterable[Path], cache_file: Path) -> FontIndex:
    """名前→ファイルの対応表。変更の無いファイルはキャッシュから読む。"""
    cached = _read_cache(cache_file)
    entries: dict[str, dict] = {}
    for path in iter_font_files(dirs):
        stat = path.stat()
        key = str(path)
        hit = cached.get(key)
        if hit and hit["mtime_ns"] == stat.st_mtime_ns and hit["size"] == stat.st_size:
            entries[key] = hit
        else:
            entries[key] = {
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "names": sorted(read_font_names(path)),
            }
    # 今回見なかったディレクトリのエントリは残す（探索先を変えて実行しても読み直しにならないように）
    merged = cached | entries
    if merged != cached:
        _write_cache(cache_file, merged)

    # 対応表は今回見つかったファイルだけから作る
    files_by_name: dict[str, list[Path]] = {}
    for key, entry in entries.items():
        for name in entry["names"]:
            files_by_name.setdefault(name.casefold(), []).append(Path(key))
    return FontIndex({name: tuple(files) for name, files in files_by_name.items()})


def resolve(index: FontIndex, names: Iterable[str]) -> FontResolution:
    files: set[Path] = set()
    missing: list[str] = []
    for name in sorted(set(names)):
        found = index.lookup(name)
        if found:
            files.update(found)
        else:
            missing.append(name)
    return FontResolution(tuple(sorted(files)), tuple(missing))


def prepare_fontsdir(files: Iterable[Path], base_dir: Path) -> Path:
    """files へのリンクだけを置いたディレクトリ。同じ組み合わせなら使い回す。"""
    # 相対パスのまま張ると、リンク先がリンク自身の位置から解決されてリンク切れになる
    unique = sorted({file.absolute() for file in files})
    digest = hashlib.sha256("\n".join(map(str, unique)).encode()).hexdigest()[:16]
    dest = base_dir / digest
    if dest.is_dir():
        return dest
    tmp = base_dir / f"{digest}.tmp{os.getpid()}"
    tmp.mkdir(parents=True)
    for i, file in enumerate(unique):
        (tmp / f"{i:03d}-{file.name}").symlink_to(file)
    try:
        tmp.rename(dest)
    except OSError:
        if not dest.is_dir():  # 別プロセスが先に作った場合以外は失敗
            raise
    return dest


def _read_cache(cache_file: Path) -> dict[str, dict]:
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("format") != _CACHE_FORMAT:
        return {}
    return data.get("files", {})


def _write_cache(cache_file: Path, entries: dict[str, dict]) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_name(f"{cache_file.name}.tmp{os.getpid()}")
    tmp.write_text(
        json.dumps({"format": _CACHE_FORMAT, "files": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(cache_file)
