"""検査を通った歌詞を合成し、ffmpeg で動画に書き出す。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pysubs2
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn

from utavideo import fonts, graph, inputs, subs, vertical
from utavideo.config import OverlayText, cache_dir
from utavideo.console import console
from utavideo.ffmpeg import run, write_text
from utavideo.project import Project, to_windows_path


def compose(
    project: Project,
    lyrics: pysubs2.SSAFile,
    duration_ms: int,
    mode: graph.Mode,
    font_index: fonts.FontIndex,
    *,
    no_vertical_fade: bool = False,
    overlay: OverlayText | None = None,
) -> pysubs2.SSAFile:
    """書き出しに使うスクリプトを作る。

    no_vertical_fade は縦用 .ass を描くとき。Vertical で始まるスタイルの行に自動のフェードを
    入れない（区間いっぱいに置く帯の文字が、繰り返し再生のつなぎ目で点滅しないようにする）。
    overlay を渡すと、曲名表示の設定をそれで上書きする（縦の書き出しは必ず渡す）。
    """
    config = project.config
    return subs.compose(
        lyrics,
        song=config.song,
        overlay=overlay if overlay is not None else config.overlay_text,
        fade_ms=config.lyrics.fade_ms,
        duration_ms=duration_ms,
        include_lyrics=mode != "preview",
        font_index=font_index,
        no_fade_style_prefix=vertical.VERTICAL_STYLE_PREFIX if no_vertical_fade else None,
    )


def frame_script(
    project: Project, lyrics: pysubs2.SSAFile, duration_ms: int, font_index: fonts.FontIndex
) -> pysubs2.SSAFile:
    """blur の真ん中に置く本編の映像に描く .ass。

    build/main.mp4 と同じ画面にする。曲名表示だけ vertical.overlay_text で決まる。
    """
    overlay = vertical.overlay_text(project.config.overlay_text, project.config.vertical)
    return compose(project, lyrics, duration_ms, "final", font_index, overlay=overlay)


@dataclass(frozen=True)
class Frame:
    """blur の画面で、ぼかした帯の上に置く本編の映像。"""

    script: pysubs2.SSAFile  # 本編の合成したスクリプト
    subtitles_path: Path  # 描画に使った .ass を書く場所


@dataclass(frozen=True)
class VideoTarget:
    """書き出す動画ごとに違うもの。ほかの設定（fps・fit・crf など）は [video] を使う。"""

    mode: graph.Mode
    size: tuple[int, int]
    focus: tuple[float, float]
    subtitles_path: Path  # 描画に使った .ass を書く場所
    output: Path
    label: str
    clip: graph.Clip | None = None  # 切り出す区間（None なら曲全体）
    frame: Frame | None = None  # None なら背景を size に合わせる画面（reframe）
    pitch: float | None = None  # inst のキー変更（rubberband に渡す音程の比）。None なら音声はそのまま


def write_video(
    project: Project,
    script: pysubs2.SSAFile,
    target: VideoTarget,
    duration_s: float,
    font_files: tuple[Path, ...],
    built_inputs: dict[str, Any] | None,
) -> Path:
    """合成したスクリプトを target.subtitles_path に書き、動画を target.output に書き出す。"""
    subtitles_path, output = target.subtitles_path, target.output
    _save_script(script, subtitles_path)

    video = project.config.video
    frame = None
    if target.frame is not None:
        _save_script(target.frame.script, target.frame.subtitles_path)
        frame = graph.Frame(
            size=video.size,
            focus=video.focus,
            subtitles=target.frame.subtitles_path.absolute(),
            frame_y=project.config.vertical.frame_y,
            fit=video.fit,
        )
    spec = graph.RenderSpec(
        mode=target.mode,
        size=target.size,
        fps=video.fps,
        duration_s=duration_s,
        audio=project.audio_path.absolute(),
        subtitles=subtitles_path.absolute(),
        fontsdir=fonts.prepare_fontsdir(font_files, cache_dir() / "fontsets"),
        background=project.background_path.absolute(),
        fit=video.fit,
        focus=target.focus,
        scale_flags=video.scale_flags,
        pad_color=video.pad_color,
        crf=video.crf,
        preset=video.preset,
        clip=target.clip,
        frame=frame,
        pitch=target.pitch,
    )
    if built_inputs is not None:
        # フォントは ffmpeg が書き出し中に読むので、その前に stat を取る
        built_inputs = inputs.with_fonts(built_inputs, font_files)
        # 書き出しが途中で終わったとき、前の記録が新しい動画のものに見えないように先に消す
        project.inputs_record.unlink(missing_ok=True)

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(target.label, total=1.0)
        run(
            graph.build_args(spec),
            output,
            total_s=duration_s,
            on_progress=lambda fraction: progress.update(task, completed=fraction),
        )
    if built_inputs is not None:
        write_text(project.inputs_record, inputs.record_text(project, built_inputs))
    console.print(f"書き出しました: {output}", markup=False)
    if windows_path := to_windows_path(output):
        console.print(f"  Windows: {windows_path}", markup=False)
    return output


def _save_script(script: pysubs2.SSAFile, path: Path) -> None:
    """描画に使う .ass を書く。ほかの出力と同じく .partial に書いてから名前を変える。"""
    write_text(path, script.to_string("ass"))
