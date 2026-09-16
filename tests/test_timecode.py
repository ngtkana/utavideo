import pytest

from utavideo.timecode import format_time, parse_time


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0:00", 0.0),
        ("1:23", 83.0),
        ("1:23.5", 83.5),
        ("1:23.05", 83.05),
        ("0:00.001", 0.001),
        ("12:00.000", 720.0),
        ("123:59", 123 * 60 + 59),
        (0, 0.0),
        (83.5, 83.5),
    ],
)
def test_parse_time(value: object, expected: float) -> None:
    assert parse_time(value) == pytest.approx(expected)


@pytest.mark.parametrize(
    "value",
    [
        "83.5",  # 秒は数で書く（文字列の "83.5" は書き間違いかもしれない）
        "1:60",
        "1:2",
        "1:23.",
        "1:23.1234",  # ミリ秒より細かくは書けない
        "0:01:23",
        "-0:01",
        "１:２３",  # 全角数字
        " 1:23",
        -1,
        float("inf"),
        float("nan"),
        True,
        None,
    ],
)
def test_parse_time_rejects(value: object) -> None:
    with pytest.raises(ValueError):
        parse_time(value)


def test_format_time() -> None:
    assert format_time(83.5) == "1:23.500"
    assert format_time(0) == "0:00.000"
    assert format_time(parse_time("12:34.567")) == "12:34.567"
