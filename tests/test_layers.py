"""utavideo.layers（[[layers]] のパス解決・区間の選別・LayerSpec への変換）。ffmpeg は要らない。"""

from pathlib import Path

from utavideo import layers
from utavideo.config import Layer

LOGO = Layer(name="logo", file=Path("assets/logo.png"), start=5.0, end=12.0)


def test_file_path_is_relative_to_root() -> None:
    assert layers.file_path(Path("/song"), LOGO) == Path("/song/assets/logo.png")


def test_file_path_keeps_an_absolute_path() -> None:
    absolute = Layer(name="logo", file=Path("/abs/logo.png"))
    assert layers.file_path(Path("/song"), absolute) == Path("/abs/logo.png")


def test_active_at_checks_the_time_range() -> None:
    assert layers.active_at(LOGO, 5.0) is True  # start は含む
    assert layers.active_at(LOGO, 11.999) is True
    assert layers.active_at(LOGO, 12.0) is False  # end は含まない
    assert layers.active_at(LOGO, 4.999) is False


def test_active_at_with_no_time_range_is_always_active() -> None:
    always = Layer(name="logo", file=Path("logo.png"))
    assert layers.active_at(always, 0.0) is True
    assert layers.active_at(always, 1_000_000.0) is True


def test_spec_resolves_the_path_and_copies_the_placement() -> None:
    spec = layers.spec(Path("/song"), LOGO)
    assert spec.file == Path("/song/assets/logo.png")
    assert (spec.scale, spec.anchor, spec.margin, spec.layer) == (1.0, "center", (0, 0), 0)
    assert (spec.start, spec.end) == (5.0, 12.0)


def test_spec_untimed_drops_the_time_range() -> None:
    # サムネイル用。区間に入るかどうかは呼び出し側（active_at）で選別済みなので、
    # -ss で読む静止画とは噛み合わない絶対時刻の enable は付けない
    spec = layers.spec(Path("/song"), LOGO, timed=False)
    assert (spec.start, spec.end) == (None, None)
