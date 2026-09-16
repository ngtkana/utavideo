"""ffmpeg / ffprobe の実行。"""

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from utavideo.errors import UtavideoError


class FFmpegError(UtavideoError):
    """ffmpeg / ffprobe が無い、または失敗した。"""


@dataclass(frozen=True)
class AudioInfo:
    duration_s: float
    has_sound: bool


def require_tools() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise FFmpegError(f"{', '.join(missing)} が見つかりません（例: sudo apt install ffmpeg）")


def probe_audio(path: Path) -> AudioInfo:
    """音源の長さと、音声ストリームが入っているか。"""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
           "format=duration:stream=index", "-of", "json", str(path)]  # fmt: skip
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(out.stdout)
        return AudioInfo(float(info["format"]["duration"]), bool(info.get("streams")))
    except subprocess.CalledProcessError as e:
        raise FFmpegError(f"{path} を読めません: {e.stderr.strip()}") from e
    except (KeyError, ValueError) as e:
        raise FFmpegError(f"{path} の長さを取得できません") from e


def probe_duration(path: Path) -> float | None:
    """GIF・動画の長さ（秒）。長さの情報が無ければ None（画像など）。"""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration = json.loads(out.stdout).get("format", {}).get("duration")
        return float(duration) if duration not in (None, "N/A") else None
    except subprocess.CalledProcessError as e:
        raise FFmpegError(f"{path} を読めません: {e.stderr.strip()}") from e
    except ValueError as e:
        raise FFmpegError(f"{path} の長さを取得できません") from e


def partial_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}.partial{output.suffix}")


def replace_partial(tmp: Path, output: Path) -> None:
    """書き終えた tmp で output を置き換える。失敗しても tmp は残す。"""
    try:
        tmp.replace(output)
    except PermissionError as e:
        # WSL の drvfs では Windows のアプリが output を開いていると、権限に関係なく EACCES になる。
        # tmp は同じフォルダに書けているので、原因はほぼこれ（docs/verification/20260916-locked-output.md）
        raise UtavideoError(
            f"{output} を置き換えられません。他のアプリ（動画プレイヤー、エクスプローラーのプレビューなど）"
            "で開かれていないか確認してください。\n"
            f"書き出したファイルは {tmp} に残っています。閉じてから再実行するか、名前を変えてください"
        ) from e


def run(
    args: Sequence[str],
    output: Path,
    *,
    total_s: float,
    on_progress: Callable[[float], None] | None = None,
    no_output_hint: str = "",
) -> None:
    """args の末尾に一時ファイル名を足して実行し、成功したときだけ output に置き換える。

    no_output_hint は、ffmpeg が正常に終わっても何も書かなかったときのエラーに添える説明。
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = partial_path(output)
    tmp.unlink(missing_ok=True)

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stderr:
        proc = subprocess.Popen(
            [*args, str(tmp)],
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and value.isdigit() and on_progress and total_s > 0:
                    on_progress(min(int(value) / 1_000_000 / total_s, 1.0))
            code = proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            tmp.unlink(missing_ok=True)
            raise
        if code != 0:
            tmp.unlink(missing_ok=True)
            stderr.seek(0)
            detail = stderr.read().strip()[-2000:]
            raise FFmpegError(f"ffmpeg が失敗しました（終了コード {code}）:\n{detail}")

    # 入力の長さを超える位置へシークすると、ffmpeg は何も書かずに終了コード 0 で終わる
    # （docs/verification/20260917-thumbnail.md）。そのまま置き換えると分かりにくいエラーになる
    if not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        hint = f"。{no_output_hint}" if no_output_hint else ""
        raise FFmpegError(f"ffmpeg は正常に終了しましたが、何も書き出しませんでした: {output}{hint}")
    replace_partial(tmp, output)
