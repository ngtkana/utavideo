"""slug の作り方と検査。"""

import pytest

from utavideo.names import (
    MAX_SLUG_BYTES,
    casefold_duplicates,
    has_date_prefix,
    legacy_name_from_title,
    slug_error,
    slug_from_dir_name,
    slug_from_title,
)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("新しい曲", "新しい曲"),
        ("A/B: C", "A-B-C"),
        ("  空白  だけ 区切る  ", "空白-だけ-区切る"),
        ("Mr.", "Mr"),
        ("...", "untitled"),
        ("   ", "untitled"),
        ("CON", "CON-1"),
        ("NUL.いい曲", "NUL-1.いい曲"),
        ("nul.mp4", "nul-1.mp4"),
    ],
)
def test_slug_from_title(title: str, expected: str) -> None:
    assert slug_from_title(title) == expected


def test_slug_from_title_is_always_usable() -> None:
    for title in (
        "A/B: C",
        "Mr.",
        "...",
        "CON",
        "nul.mp4",
        "com1." + "あ" * 500,
        "x" * 500,
        "あ" * 500,
        '"<>|',
        "-先頭",
    ):
        assert slug_error(slug_from_title(title)) is None, title


def test_slug_from_title_cuts_by_bytes_without_breaking_a_character() -> None:
    slug = slug_from_title("あ" * 100)
    # ファイル名の上限はバイト数。切ったところで文字が壊れない
    assert len(slug.encode()) <= MAX_SLUG_BYTES
    assert slug == "あ" * (MAX_SLUG_BYTES // 3)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("20260913 新しい曲", "新しい曲"),
        ("20240114-曲名", "曲名"),
        ("日付なし", "日付なし"),
        ("20260916", "20260916"),
        ("123456789-song", "123456789-song"),  # 数字が9桁続くものは日付ではない
    ],
)
def test_slug_from_dir_name(name: str, expected: str) -> None:
    assert slug_from_dir_name(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [("20260916-song", True), ("20260916 song", True), ("song", False), ("123456789-song", False)],
)
def test_has_date_prefix(name: str, expected: bool) -> None:
    assert has_date_prefix(name) == expected


def test_legacy_name_from_title() -> None:
    """song.slug より前に公開した動画を見分けるための、以前の規則。"""
    assert legacy_name_from_title('A/B "C"') == "A_B _C_"
    assert legacy_name_from_title("   ") == "untitled"


@pytest.mark.parametrize("slug", ["song", "曲名", "20260916-song", "v1.0", "a" * MAX_SLUG_BYTES])
def test_usable_slugs(slug: str) -> None:
    assert slug_error(slug) is None


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "a/b",
        "a:b",
        'a"b',
        "Mr.",
        "末尾の空白 ",
        "CON",
        "con.mp4",
        "-先頭のハイフン",
        "a" * (MAX_SLUG_BYTES + 1),
        "あ" * (MAX_SLUG_BYTES // 3 + 1),
    ],
)
def test_unusable_slugs(slug: str) -> None:
    assert slug_error(slug) is not None


def test_casefold_duplicates_reports_later_names() -> None:
    assert casefold_duplicates(["main", "square", "Main", "SQUARE", "x"]) == ["Main", "SQUARE"]
    assert casefold_duplicates(["a", "b"]) == []
