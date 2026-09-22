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


class NoOutputError(FFmpegError):
    """ffmpeg が正常に終わったのに、何も書き出さなかった。"""


@dataclass(frozen=True)
class AudioInfo:
    duration_s: float
    has_sound: bool


def require_tools(*, subtitles: bool = True, rubberband: bool = False) -> None:
    """使えなければ止める。歌詞を描かない用途は subtitles=False で libass を要求しない。

    キー変更を使う用途（inst）は rubberband=True で librubberband を要求する。
    """
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise FFmpegError(f"{', '.join(missing)} が見つかりません（例: sudo apt install ffmpeg）")
    if subtitles and (error := subtitles_filter_error()) is not None:
        raise FFmpegError(error)
    if rubberband and (error := rubberband_filter_error()) is not None:
        raise FFmpegError(error)


def subtitles_filter_error() -> str | None:
    """ffmpeg で subtitles フィルタ（libass）を使えない理由と直し方。使えるなら None。"""
    # フィルタが無くても終了コードは 0 で "Unknown filter" と出るだけなので、見出しの有無で判定する。
    # 一覧の -filters（40KB ほど）でも同じことはできるが、どちらも 20ms なので出力の小さい方にした。
    # 手元の 6.1 は stdout に出すが、stderr に出すビルドで誤判定しないよう両方を見る
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg, "-hide_banner", "-h", "filter=subtitles"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as e:
        return f"{ffmpeg} を実行できません: {e}"
    # 共有ライブラリが足りないなどで動かない ffmpeg を「libass 非対応」と誤診しないよう、終了コードを先に見る
    if out.returncode != 0:
        detail = (out.stderr.strip() or out.stdout.strip())[-500:]
        return f"{ffmpeg} を実行できません（終了コード {out.returncode}）: {detail}"
    if "Filter subtitles" in out.stdout + out.stderr:
        return None
    return (
        f"{ffmpeg} が subtitles フィルタ（libass）に対応していないので、歌詞を描画できません。"
        "libass 付きの ffmpeg を入れてください"
        "（Ubuntu: sudo apt install ffmpeg、macOS の Homebrew: brew install ffmpeg-full）"
    )


def rubberband_filter_error() -> str | None:
    """ffmpeg で rubberband フィルタ（librubberband）を使えない理由と直し方。使えるなら None。"""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg, "-hide_banner", "-h", "filter=rubberband"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except OSError as e:
        return f"{ffmpeg} を実行できません: {e}"
    if out.returncode != 0:
        detail = (out.stderr.strip() or out.stdout.strip())[-500:]
        return f"{ffmpeg} を実行できません（終了コード {out.returncode}）: {detail}"
    if "Filter rubberband" in out.stdout + out.stderr:
        return None
    return (
        f"{ffmpeg} が rubberband フィルタ（librubberband）に対応していないので、キーを変えられません。"
        "librubberband 付きの ffmpeg を入れてください"
        "（Ubuntu: 既定の ffmpeg パッケージには含まれないことが多いのでソースビルドか PPA を検討、"
        "macOS の Homebrew: brew install ffmpeg-full）"
    )


def _probe_format(path: Path, entries: str, *extra: str) -> dict:
    cmd = ["ffprobe", "-v", "error", *extra, "-show_entries", entries, "-of", "json", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(out.stdout)
    except subprocess.CalledProcessError as e:
        raise FFmpegError(f"{path} を読めません: {e.stderr.strip()}") from e


def probe_audio(path: Path) -> AudioInfo:
    """音源の長さと、音声ストリームが入っているか。"""
    info = _probe_format(path, "format=duration:stream=index", "-select_streams", "a")
    try:
        return AudioInfo(float(info["format"]["duration"]), bool(info.get("streams")))
    except (KeyError, ValueError) as e:
        raise FFmpegError(f"{path} の長さを取得できません") from e


def probe_duration(path: Path) -> float | None:
    """GIF・動画の長さ（秒）。長さの情報が無ければ None（画像など）。"""
    duration = _probe_format(path, "format=duration").get("format", {}).get("duration")
    try:
        return float(duration) if duration not in (None, "N/A") else None
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


def write_text(path: Path, text: str) -> None:
    """テキストを .partial に書いてから名前を変える。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = partial_path(path)
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_partial(tmp, path)


def run(
    args: Sequence[str],
    output: Path,
    *,
    total_s: float,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """args の末尾に一時ファイル名を足して実行し、成功したときだけ output に置き換える。

    ffmpeg が正常に終わっても何も書かなかったときは NoOutputError（原因の説明は呼び出し側で足す）。
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
        raise NoOutputError(f"ffmpeg は正常に終了しましたが、何も書き出しませんでした: {output}")
    replace_partial(tmp, output)
