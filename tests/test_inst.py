from pathlib import Path

import pytest

from utavideo import inst
from utavideo.config import Score
from utavideo.errors import UtavideoError
from utavideo.score import NoteEvent, RenderedScore


@pytest.mark.parametrize(("key", "label"), [(0, "0"), (2, "+2"), (-1, "-1"), (-12, "-12")])
def test_key_label(key: int, label: str) -> None:
    assert inst.key_label(key) == label


def test_output_path_uses_the_slug_and_key_label() -> None:
    build_dir = Path("/a/build")
    assert inst.output_path(build_dir, "song", -1) == build_dir / "inst" / "song-key-1.mp4"
    assert inst.output_path(build_dir, "song", 2) == build_dir / "inst" / "song-key+2.mp4"
    assert inst.output_path(build_dir, "song", 0) == build_dir / "inst" / "song-key0.mp4"


def test_work_ass_path_uses_the_key_label() -> None:
    work_dir = Path("/a/build/.work")
    assert inst.work_ass_path(work_dir, -1) == work_dir / "inst" / "key-1.ass"


def test_keys_in_build_is_empty_when_the_directory_is_missing(tmp_path: Path) -> None:
    assert inst.keys_in_build(tmp_path / "build", "song") == []


def test_keys_in_build_scans_existing_files_only(tmp_path: Path) -> None:
    build_dir = tmp_path / "build"
    (build_dir / "inst").mkdir(parents=True)
    for key in (-1, 0, 2):
        inst.output_path(build_dir, "song", key).write_bytes(b"video")
    (build_dir / "inst" / "song-keyfoo.mp4").write_bytes(b"not a key")  # 命名規則に合わないものは無視する
    (build_dir / "inst" / "other-key0.mp4").write_bytes(b"another song")  # 別の曲は対象外

    assert inst.keys_in_build(build_dir, "song") == [-1, 0, 2]


def test_keys_in_build_handles_slugs_with_glob_metacharacters(tmp_path: Path) -> None:
    """slug は [ ] などの glob のメタ文字を含みうる（song.slug は禁止していない）。"""
    build_dir = tmp_path / "build"
    slug = "test[live]"
    inst.output_path(build_dir, slug, -1).parent.mkdir(parents=True)
    inst.output_path(build_dir, slug, -1).write_bytes(b"video")

    assert inst.keys_in_build(build_dir, slug) == [-1]


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


def test_score_image_path_is_split_by_key() -> None:
    """楽譜は--keysの移調に連動して中身が変わる（issue #144）ので、キーごとに分ける。"""
    work_dir = Path("/a/build/.work")
    assert inst.score_image_path(work_dir, -1) == work_dir / "inst" / "score-key-1.png"
    assert inst.score_image_path(work_dir, 2) == work_dir / "inst" / "score-key+2.png"
    assert inst.score_image_path(work_dir, 0) == work_dir / "inst" / "score-key0.png"


def test_score_overlay_shifts_time_by_the_first_bar_offset() -> None:
    config_score = Score(file=Path("/a/song.mscz"), first_bar_offset_s=1.5, play_x=0.5, y=100)
    rendered = RenderedScore(
        png=b"", width=200, height=50, events=[NoteEvent(x=10.0, time_s=0.0), NoteEvent(x=20.0, time_s=2.0)]
    )

    overlay = inst.score_overlay(config_score, Path("/a/score.png"), rendered, video_size=(1000, 1000))

    assert overlay.events == (NoteEvent(x=10.0, time_s=1.5), NoteEvent(x=20.0, time_s=3.5))
    assert overlay.play_x == 500  # play_x=0.5 * 幅1000
    assert overlay.y == 100  # y を指定したときは、自動配置せずそのまま使う
    assert overlay.image == Path("/a/score.png")


def test_score_overlay_rounds_play_x_to_the_nearest_pixel() -> None:
    config_score = Score(file=Path("/a/song.mscz"), play_x=1 / 3)
    rendered = RenderedScore(png=b"", width=200, height=50, events=[NoteEvent(x=0.0, time_s=0.0)])

    overlay = inst.score_overlay(config_score, Path("/a/score.png"), rendered, video_size=(1920, 1080))

    assert overlay.play_x == round(1920 / 3)


def test_score_overlay_centers_vertically_when_y_is_omitted() -> None:
    """yを省略すると、画面の縦方向の中央に自動配置する（曲名は上部、--lyricsの歌詞は下部にあり
    重ならないため。issue #145）。"""
    config_score = Score(file=Path("/a/song.mscz"))
    rendered = RenderedScore(png=b"", width=9000, height=120, events=[NoteEvent(x=0.0, time_s=0.0)])

    overlay = inst.score_overlay(config_score, Path("/a/score.png"), rendered, video_size=(1920, 1080))

    assert overlay.y == (1080 - 120) // 2
