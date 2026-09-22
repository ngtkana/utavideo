"""歌唱練習用のカラオケ動画（inst）のパスと、キーの解釈。"""

from pathlib import Path

from utavideo.config import Inst, OverlayText
from utavideo.errors import UtavideoError


def directory(build_dir: Path) -> Path:
    return build_dir / "inst"


def overlay_text(base: OverlayText, config: Inst) -> OverlayText:
    """歌唱練習用の動画に描く曲名表示。base のスタイルを使い、文字は inst 用に差し替える。

    練習用の動画は、これが何のキーか分からないと意味が無いので、必ず表示する。
    """
    return base.model_copy(update={"text": config.text, "enabled": True})


def key_label(key: int) -> str:
    """ファイル名・画面表示に使う符号付きの文字列（+2 / -1 / 0）。"""
    return f"+{key}" if key > 0 else str(key)


def output_path(build_dir: Path, key: int) -> Path:
    return directory(build_dir) / f"key{key_label(key)}.mp4"


def work_ass_path(work_dir: Path, key: int) -> Path:
    return work_dir / "inst" / f"key{key_label(key)}.ass"


def pitch_ratio(key: int) -> float:
    """半音単位のキーを rubberband の pitch（周波数の比）に変換する。"""
    return 2 ** (key / 12)


def parse_keys(raw: str) -> list[int]:
    """--keys の値をパースする。空・整数でない・重複はエラー。"""
    tokens = [t.strip() for t in raw.split(",")]
    if not raw.strip() or any(not t for t in tokens):
        raise UtavideoError(f"--keys はカンマ区切りの整数で指定してください（例: --keys=-1,-2,-3）: {raw!r}")
    try:
        keys = [int(t) for t in tokens]
    except ValueError as e:
        raise UtavideoError(f"--keys の値が整数ではありません（例: --keys=-1,-2,-3）: {raw!r}") from e
    if len(set(keys)) != len(keys):
        raise UtavideoError(f"--keys の値が重複しています: {raw}")
    return keys
