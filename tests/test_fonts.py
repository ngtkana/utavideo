import json
import unicodedata
from pathlib import Path

import pytest

from tests.conftest import MakeFont
from utavideo import fonts
from utavideo.errors import UtavideoError


def test_index_looks_up_family_case_insensitively(tmp_path: Path, make_font: MakeFont) -> None:
    font = make_font(tmp_path / "fonts" / "TestSans.ttf", "Test Sans")
    index = fonts.load_index([tmp_path / "fonts"], tmp_path / "cache.json")
    assert index.lookup("test sans") == (font,)
    assert index.lookup("Other") == ()


def test_index_reuses_cache_for_unchanged_files(
    tmp_path: Path, make_font: MakeFont, monkeypatch: pytest.MonkeyPatch
) -> None:
    font = make_font(tmp_path / "fonts" / "TestSans.ttf", "Test Sans")
    cache = tmp_path / "cache.json"
    fonts.load_index([tmp_path / "fonts"], cache)

    def fail(path: Path) -> set[str]:
        pytest.fail(f"キャッシュがあるのに読み直した: {path}")

    monkeypatch.setattr(fonts, "read_font_names", fail)
    assert fonts.load_index([tmp_path / "fonts"], cache).lookup("Test Sans") == (font,)


def test_index_keeps_cache_of_directories_not_scanned(tmp_path: Path, make_font: MakeFont) -> None:
    font = make_font(tmp_path / "a" / "A.ttf", "Font A")
    cache = tmp_path / "cache.json"
    fonts.load_index([tmp_path / "a"], cache)

    (tmp_path / "b").mkdir()
    index = fonts.load_index([tmp_path / "b"], cache)
    assert str(font) in json.loads(cache.read_text(encoding="utf-8"))["files"]
    assert index.lookup("Font A") == ()  # 対応表に入るのは、今回見たディレクトリのものだけ


def test_index_ignores_unicode_normalization(tmp_path: Path, make_font: MakeFont) -> None:
    # macOS で名前をコピーすると NFD（「ゴ」が コ ＋ 濁点）になることがある。フォント側の名前は NFC
    nfc = unicodedata.normalize("NFC", "テストゴシック")
    font = make_font(tmp_path / "nfc" / "TestGothic.ttf", nfc)
    index = fonts.load_index([tmp_path / "nfc"], tmp_path / "cache.json")
    assert index.lookup(nfc) == (font,)
    assert index.lookup(unicodedata.normalize("NFD", nfc)) == (font,)


def test_index_ignores_unicode_normalization_in_the_font(tmp_path: Path, make_font: MakeFont) -> None:
    nfc = unicodedata.normalize("NFC", "テストゴシック")
    font = make_font(tmp_path / "nfd" / "TestGothic.ttf", unicodedata.normalize("NFD", nfc))
    index = fonts.load_index([tmp_path / "nfd"], tmp_path / "cache.json")
    assert index.lookup(nfc) == (font,)


def test_broken_font_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "fonts").mkdir()
    (tmp_path / "fonts" / "broken.ttf").write_bytes(b"not a font")
    index = fonts.load_index([tmp_path / "fonts"], tmp_path / "cache.json")
    assert index.files_by_name == {}


def test_resolve_and_prepare_fontsdir(tmp_path: Path, make_font: MakeFont) -> None:
    a = make_font(tmp_path / "fonts" / "A.ttf", "Font A")
    b = make_font(tmp_path / "fonts" / "sub" / "B.ttf", "Font B")
    index = fonts.load_index([tmp_path / "fonts"], tmp_path / "cache.json")

    resolution = fonts.resolve(index, ["Font B", "Font A", "Missing"])
    assert resolution.files == tuple(sorted([a, b]))
    assert resolution.missing == ("Missing",)

    fontsdir = fonts.prepare_fontsdir(resolution.files, tmp_path / "sets")
    assert sorted(p.resolve() for p in fontsdir.iterdir()) == sorted([a, b])
    assert fonts.prepare_fontsdir(reversed(resolution.files), tmp_path / "sets") == fontsdir


def test_fontsdir_links_work_for_relative_paths(
    tmp_path: Path, make_font: MakeFont, monkeypatch: pytest.MonkeyPatch
) -> None:
    font = make_font(tmp_path / "fonts" / "TestSans.ttf", "Test Sans")
    monkeypatch.chdir(tmp_path)
    index = fonts.load_index([Path("fonts")], tmp_path / "cache.json")

    fontsdir = fonts.prepare_fontsdir(fonts.resolve(index, ["Test Sans"]).files, tmp_path / "sets")
    link = next(iter(fontsdir.iterdir()))
    assert link.is_file(), "リンク先を解決できない（相対パスのまま symlink を張っている）"
    assert link.resolve() == font.resolve()


def test_cache_write_reports_locked_file(
    tmp_path: Path, make_font: MakeFont, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_font(tmp_path / "fonts" / "TestSans.ttf", "Test Sans")

    def locked(self: Path, target: Path) -> Path:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(UtavideoError, match="他のアプリ"):
        fonts.load_index([tmp_path / "fonts"], tmp_path / "cache.json")
    assert list(tmp_path.glob("cache.json*")) == []
