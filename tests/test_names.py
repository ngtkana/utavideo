"""slug の作り方と検査。"""

import pytest

from utavideo.names import MAX_SLUG_LEN, slug_error, slug_from_dir_name, slug_from_title


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
        ("nul.mp4", "nul.mp4-1"),
    ],
)
def test_slug_from_title(title: str, expected: str) -> None:
    assert slug_from_title(title) == expected


def test_slug_from_title_is_always_usable() -> None:
    for title in ("A/B: C", "Mr.", "...", "CON", "x" * 500, '"<>|'):
        assert slug_error(slug_from_title(title)) is None, title


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("20260913 新しい曲", "新しい曲"),
        ("20240114-曲名", "曲名"),
        ("日付なし", "日付なし"),
        ("20260916", "20260916"),
    ],
)
def test_slug_from_dir_name(name: str, expected: str) -> None:
    assert slug_from_dir_name(name) == expected


@pytest.mark.parametrize("slug", ["song", "曲名", "20260916-song", "v1.0", "a" * MAX_SLUG_LEN])
def test_usable_slugs(slug: str) -> None:
    assert slug_error(slug) is None


@pytest.mark.parametrize(
    "slug", ["", "a/b", "a:b", 'a"b', "Mr.", "末尾の空白 ", "CON", "con.mp4", "a" * (MAX_SLUG_LEN + 1)]
)
def test_unusable_slugs(slug: str) -> None:
    assert slug_error(slug) is not None
