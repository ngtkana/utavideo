"""utavideo preview（--at・--duration・--watch）の実装。

一瞬・短い区間だけをすばやく確認するための書き出しと、ファイルの変更検知（--watch）。
preview-bg（曲全体の Aegisub 用の下敷き）とは別に、utavideo.toml の数値・スタイルの
調整のたびに本番の build を待たずに確かめる用途（issue #113）。

検査（check 相当）は行わない。プレビュー用途では「今の状態」をそのまま見せたいため
（エラーがあっても、書き出せるところまでは書き出す）。ただし ffmpeg が失敗するような
致命的な状態（--duration が短すぎる等）は、ffmpeg を呼ぶ前に分かりやすいエラーにする。
"""

import math
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import pysubs2

from utavideo import fonts, graph, layers
from utavideo.analyze import FontSearch, analyze
from utavideo.config import Video, cache_dir
from utavideo.console import console, err_console
from utavideo.errors import UtavideoError
from utavideo.ffmpeg import NoOutputError, run, write_text
from utavideo.project import Project
from utavideo.render import VideoTarget, compose, write_video
from utavideo.subs import Issue

# --watch のポーリング間隔（秒）。新しい依存を増やさず、素朴な mtime ポーリングで足りる（issue #113）
POLL_INTERVAL_S = 1.0


def _print_issue(issue: Issue) -> None:
    tag = "[bold red]エラー[/]" if issue.level == "error" else "[yellow]警告[/]"
    err_console.print(tag, end=" ")
    err_console.print(issue.message, markup=False)


def _frame(seconds: float, fps: int) -> int:
    """秒をいちばん近いフレームの番号にする（shorts.clip_frames と同じ丸め方）。"""
    return math.floor(seconds * fps + 0.5)


def clip_for(at: float, duration_s: float, fps: int) -> graph.Clip:
    """--at・--duration をフレームに丸めた区間にする。丸めると長さ 0 になるときは UtavideoError。"""
    start_frame, end_frame = _frame(at, fps), _frame(at + duration_s, fps)
    if end_frame <= start_frame:
        raise UtavideoError(f"--duration が短すぎます（{fps}fps で 1 フレーム未満になります）")
    return graph.Clip(start_frame, end_frame, (0, 0))


def render(project: Project, search: FontSearch, at: float, duration_s: float | None) -> Path:
    """--at（と、あれば --duration）に沿った静止画・動画を書き出し、出力先を返す。"""
    analysis = analyze(project, "final", search)
    for issue in analysis.issues:
        _print_issue(issue)
    if analysis.lyrics is None or analysis.duration_s is None or analysis.font_index is None:
        raise UtavideoError("音源または歌詞が読めないため、プレビューを作れません")

    duration_ms = round(analysis.duration_s * 1000)
    script = compose(project, analysis.lyrics, duration_ms, "final", analysis.font_index)
    video = project.config.video
    if duration_s is None:
        return _render_still(project, script, video, at, analysis.font_files)

    clip = clip_for(at, duration_s, video.fps)
    layer_specs = tuple(layers.spec(project.root, layer) for layer in project.config.layers)
    target = VideoTarget(
        "preview",
        video.size,
        video.focus,
        project.work_dir / "preview.ass",
        project.preview_video_output,
        "preview",
        clip=clip,
        layers=layer_specs,
    )
    return write_video(project, script, target, clip.duration_s(video.fps), analysis.font_files, None)


def _render_still(
    project: Project, script: pysubs2.SSAFile, video: Video, at: float, font_files: tuple[Path, ...]
) -> Path:
    subtitles_path = project.work_dir / "preview.ass"
    write_text(subtitles_path, script.to_string("ass"))
    fontsdir = fonts.prepare_fontsdir(font_files, cache_dir() / "fontsets")
    # -ss で読む素材は t が 0 秒近辺になるので、区間の判定はここで済ませ enable には渡さない
    # （utavideo.layers.spec の docstring・thumbnail の _write_thumbnail と同じ考え方）
    active_layers = tuple(
        layers.spec(project.root, layer, timed=False)
        for layer in project.config.layers
        if layers.active_at(layer, at)
    )
    spec = graph.StillSpec(
        size=video.size,
        background=project.background_path.absolute(),
        focus=video.focus,
        at=at,
        subtitles=subtitles_path.absolute(),
        fontsdir=fontsdir,
        fit=video.fit,
        scale_flags=video.scale_flags,
        pad_color=video.pad_color,
        layers=active_layers,
    )
    output = project.preview_still_output
    try:
        run(graph.build_still_args(spec), output, total_s=0)
    except NoOutputError as e:
        raise NoOutputError(
            f"{e}。背景の終わり近くの --at では、それ以降のフレームが無いことがあります"
        ) from e
    # 動画（write_video）は書き出しに成功したら自分で表示するが、静止画はここでしか表示しないので出す
    console.print(f"書き出しました: {output}", markup=False)
    return output


def watched_files(project: Project) -> tuple[Path, ...]:
    """--watch が監視するファイル（設定・歌詞・[[layers]] の素材・背景）。"""
    return (
        project.config_path,
        project.lyrics_path,
        project.background_path,
        *(layers.file_path(project.root, layer) for layer in project.config.layers),
    )


def _stamp(path: Path) -> tuple[int, int] | None:
    """大きさと更新時刻。ファイルが無ければ None（project.py・inputs.py と同じ考え方）。"""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def snapshot(files: Iterable[Path]) -> dict[Path, tuple[int, int] | None]:
    """files の (大きさ, 更新時刻) の組。watch はこれが変わったかどうかで再生成を判断する。"""
    return {path: _stamp(path) for path in files}


def watch(root: Path, on_change: Callable[[Project], None], *, interval_s: float = POLL_INTERVAL_S) -> None:
    """root の監視対象ファイルをポーリングし、変わるたびに on_change(project) を呼ぶ（最初の1回も呼ぶ）。

    utavideo.toml が一時的に壊れている間・on_change が失敗した間も、直ればまた検知できるよう、
    エラーを表示してポーリングを続ける。Ctrl+C（KeyboardInterrupt）はここでは扱わず、呼び出し側に返す。
    """
    previous: dict[Path, tuple[int, int] | None] | None = None
    while True:
        try:
            project = Project.load(root)
            current = snapshot(watched_files(project))
        except UtavideoError as e:
            err_console.print("[yellow]警告[/]", end=" ")
            err_console.print(str(e), markup=False)
        else:
            if current != previous:
                try:
                    on_change(project)
                except UtavideoError as e:
                    err_console.print("[bold red]エラー[/]", end=" ")
                    err_console.print(str(e), markup=False)
                previous = current
        time.sleep(interval_s)
