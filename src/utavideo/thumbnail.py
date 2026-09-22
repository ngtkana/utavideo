"""utavideo.toml の [[thumbnails]] 1本ごとの出力先のパスと、size・focus など
省略時に [video] から引き継ぐ値を決める。
"""

from pathlib import Path

from utavideo.config import Focus, Thumbnail, VideoSize


def directory(build_dir: Path) -> Path:
    return build_dir / "thumbnail"


def output_path(build_dir: Path, thumbnail: Thumbnail) -> Path:
    return directory(build_dir) / f"{thumbnail.name}.png"


def bg_output_path(build_dir: Path, thumbnail: Thumbnail) -> Path:
    # 別のフォルダに置く。<name>-bg.png だと、name = "main-bg" のサムネイルとぶつかる
    return directory(build_dir) / "bg" / f"{thumbnail.name}.png"


def file_path(root: Path, thumbnail: Thumbnail) -> Path:
    file = thumbnail.file
    return file if file.is_absolute() else root / file


def size(thumbnail: Thumbnail, video_size: VideoSize) -> tuple[int, int]:
    return thumbnail.size or video_size


def focus(thumbnail: Thumbnail, video_focus: Focus) -> Focus:
    return thumbnail.focus or video_focus
