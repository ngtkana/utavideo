from pathlib import Path

import pytest

from utavideo import inst
from utavideo.errors import UtavideoError


@pytest.mark.parametrize(("key", "label"), [(0, "0"), (2, "+2"), (-1, "-1"), (-12, "-12")])
def test_key_label(key: int, label: str) -> None:
    assert inst.key_label(key) == label


def test_output_path_uses_the_key_label() -> None:
    build_dir = Path("/a/build")
    assert inst.output_path(build_dir, -1) == build_dir / "inst" / "key-1.mp4"
    assert inst.output_path(build_dir, 2) == build_dir / "inst" / "key+2.mp4"
    assert inst.output_path(build_dir, 0) == build_dir / "inst" / "key0.mp4"


def test_work_ass_path_uses_the_key_label() -> None:
    work_dir = Path("/a/build/.work")
    assert inst.work_ass_path(work_dir, -1) == work_dir / "inst" / "key-1.ass"


@pytest.mark.parametrize(("key", "ratio"), [(0, 1.0), (12, 2.0), (-12, 0.5), (24, 4.0)])
def test_pitch_ratio(key: int, ratio: float) -> None:
    assert inst.pitch_ratio(key) == pytest.approx(ratio)


def test_parse_keys_reads_comma_separated_integers() -> None:
    assert inst.parse_keys("-1,-2,-3") == [-1, -2, -3]
    assert inst.parse_keys("2") == [2]
    assert inst.parse_keys(" -1 , 2 ") == [-1, 2]


@pytest.mark.parametrize(
    "raw",
    ["", "  ", "-1,,2", "-1,x,2", "-1,-1"],
)
def test_parse_keys_rejects_bad_input(raw: str) -> None:
    with pytest.raises(UtavideoError):
        inst.parse_keys(raw)
