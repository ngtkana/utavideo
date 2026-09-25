"""utavideo.toml の [[layers]] 1個ごとのファイルパスと、区間・overlay 用の値の変換。"""

from pathlib import Path

from utavideo import graph
from utavideo.config import Layer


def file_path(root: Path, layer: Layer) -> Path:
    file = layer.file
    return file if file.is_absolute() else root / file


def active_at(layer: Layer, at: float) -> bool:
    """at 秒（曲の絶対時刻）にこのレイヤーが表示されるか（サムネイルの選別に使う）。"""
    after_start = layer.start is None or at >= layer.start
    before_end = layer.end is None or at < layer.end
    return after_start and before_end


def spec(root: Path, layer: Layer, *, timed: bool = True) -> graph.LayerSpec:
    """Layer 設定から LayerSpec を作る。

    timed=False は静止画（サムネイル）向け：区間は呼び出し側（active_at）で判定済みなので、
    overlay の enable には渡さない。サムネイルの素材は -ss で読むため、そのままだと
    t が 0 秒近辺になり、曲の絶対時刻の start・end と噛み合わない（graph.frame_input 参照）。
    """
    return graph.LayerSpec(
        file=file_path(root, layer).absolute(),
        scale=layer.scale,
        anchor=layer.anchor,
        margin=layer.margin,
        layer=layer.layer,
        start=layer.start if timed else None,
        end=layer.end if timed else None,
    )
