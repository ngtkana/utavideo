"""build/main.mp4 を書き出したときの入力の記録と、release のときの比較。

release が止まるのは、確かめた動画と描画に効く入力が違うときだけにしたい。
更新時刻では、概要欄を書き足しただけ・保存し直しただけでも止まってしまうので、中身で比べる。
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from utavideo.config import PROJECT_CONFIG_NAME, rendered_values
from utavideo.project import Project

_FORMAT = 1
FONTS = "フォント"


def _files(project: Project) -> list[tuple[str, Path]]:
    return [
        (PROJECT_CONFIG_NAME, project.config_path),
        ("audio.file", project.audio_path),
        ("video.background", project.background_path),
        ("lyrics.file", project.lyrics_path),
    ]


def snapshot(project: Project, font_files: Iterable[Path]) -> dict[str, Any]:
    """描画に効く入力の要約。値は JSON にできる形で、記録を読み戻したものとそのまま比べられる。"""
    values: dict[str, Any] = {name: _file_digest(path) for name, path in _files(project)}
    # utavideo.toml は書き方ではなく、読み込んだ値のうち描画に効くもので比べる
    config = json.dumps(rendered_values(project.config), ensure_ascii=False, sort_keys=True)
    values[PROJECT_CONFIG_NAME] = hashlib.sha256(config.encode()).hexdigest()
    # 中身を読むと重いので、パス・大きさ・更新時刻で代える（issue #26）
    unique = sorted({path.absolute() for path in font_files})
    values[FONTS] = [[str(path), *_stamp(path)] for path in unique]
    return values


def record_text(project: Project, inputs: dict[str, Any]) -> str:
    """書き出し終えた build/main.mp4 と、その入力の記録。"""
    data = {"format": _FORMAT, "video": _stamp(project.main_output), "inputs": inputs}
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def stale_inputs(project: Project) -> str | None:
    """build/main.mp4 を書き出した後に変わった入力の説明。変わっていなければ None。"""
    recorded = _read_record(project)
    if recorded is None:
        # 記録の無い build（記録を始める前のものなど）は、更新時刻で比べる
        built_at = project.main_output.stat().st_mtime
        files = _files(project)
        newer = [name for name, path in files if path.is_file() and path.stat().st_mtime > built_at]
        return f"build/main.mp4 より新しい入力があります（{', '.join(newer)}）" if newer else None
    fonts = [Path(entry[0]) for entry in recorded.get(FONTS, [])]
    # 記録に無い入力（形式を変えたときなど）も、変わったものとして扱う
    changed = [name for name, value in snapshot(project, fonts).items() if recorded.get(name) != value]
    return (
        f"build/main.mp4 を書き出した後に変わった入力があります（{', '.join(changed)}）" if changed else None
    )


def _read_record(project: Project) -> dict[str, Any] | None:
    """使える記録の inputs。無い・読めない・別の動画のものなら None。"""
    try:
        data = json.loads(project.inputs_record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != _FORMAT:
        return None
    # build/main.mp4 を別の手段で差し替えていたら、記録はその動画のものではない
    if data.get("video") != _stamp(project.main_output):
        return None
    inputs = data.get("inputs")
    return inputs if isinstance(inputs, dict) else None


def _file_digest(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    except OSError:
        return None


def _stamp(path: Path) -> list[int | None]:
    """大きさと更新時刻。ファイルが無ければ None の組。"""
    try:
        stat = path.stat()
    except OSError:
        return [None, None]
    return [stat.st_size, stat.st_mtime_ns]
