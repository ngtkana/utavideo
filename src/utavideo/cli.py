"""utavideo コマンド。"""

import functools
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, NoReturn

import pysubs2
import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn

from utavideo import fonts, graph, layout, subs
from utavideo.config import cache_dir, load_user_config
from utavideo.errors import UtavideoError
from utavideo.ffmpeg import partial_path, probe_duration, require_tools, run
from utavideo.project import (
    Project,
    ScaffoldResult,
    find_project_root,
    project_dir_name,
    scaffold,
    title_from_dir_name,
    to_windows_path,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="utavideo.toml と歌詞 .ass から歌動画を書き出す。",
)
console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

ProjectOption = Annotated[
    Path | None,
    typer.Option("--project", "-C", help="曲フォルダ。省略時はカレントディレクトリから上へ探す。"),
]


def _handle_errors[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except UtavideoError as e:
            _fail(str(e))

    return wrapper


def _fail(message: str) -> NoReturn:
    err_console.print("[bold red]エラー[/]", end=" ")
    err_console.print(message, markup=False)
    raise typer.Exit(1)


def _print_issues(issues: list[subs.Issue]) -> None:
    for issue in issues:
        tag = "[bold red]エラー[/]" if issue.level == "error" else "[yellow]警告[/]"
        err_console.print(tag, end=" ")
        err_console.print(issue.message, markup=False)


def _load_project(project_dir: Path | None) -> Project:
    return Project.load(find_project_root(project_dir or Path.cwd()))


@dataclass(frozen=True)
class Analysis:
    issues: list[subs.Issue]
    duration_s: float | None
    lyrics: pysubs2.SSAFile | None
    font_files: tuple[Path, ...]

    @property
    def ok(self) -> bool:
        return all(issue.level != "error" for issue in self.issues)


def analyze(project: Project, mode: graph.Mode) -> Analysis:
    """書き出しに必要なものが揃っているかを調べる。preview では歌詞の行の中身は問わない。"""
    config = project.config
    issues: list[subs.Issue] = []

    for label, path in [
        ("audio.file", project.audio_path),
        ("lyrics.file", project.lyrics_path),
        *([("video.background", project.background_path)] if mode != "overlay" else []),
    ]:
        if not path.is_file():
            issues.append(subs.Issue("error", f"{label} のファイルがありません: {path}"))
    background_ext = project.background_path.suffix.lower()
    if mode != "overlay" and background_ext not in graph.IMAGE_EXTS | graph.ANIMATED_EXTS:
        issues.append(subs.Issue("error", f"video.background の形式に対応していません: {background_ext}"))

    duration_s = probe_duration(project.audio_path) if project.audio_path.is_file() else None
    lyrics = subs.load(project.lyrics_path) if project.lyrics_path.is_file() else None
    if lyrics is None or duration_s is None:
        return Analysis(issues, duration_s, lyrics, ())

    duration_ms = round(duration_s * 1000)
    target = lyrics if mode != "preview" else subs.without_events(lyrics)
    issues += subs.lint(target, size=config.video.size, duration_ms=duration_ms, overlay=config.overlay_text)

    script = _compose(project, lyrics, duration_ms, mode)
    font_dirs = load_user_config().font_dirs
    cache_file = cache_dir() / "fonts.json"
    if not cache_file.exists():
        console.print("フォント一覧を作成しています（初回のみ時間がかかります）…")
    index = fonts.load_index(font_dirs, cache_file)
    resolution = fonts.resolve(index, subs.used_fonts(script))
    for name in resolution.missing:
        searched = ", ".join(map(str, font_dirs)) or "（なし）"
        issues.append(subs.Issue("error", f"フォント {name!r} が見つかりません（探した場所: {searched}）"))
    issues += layout.overflows(script, index.lookup)
    return Analysis(issues, duration_s, lyrics, resolution.files)


def _compose(project: Project, lyrics: pysubs2.SSAFile, duration_ms: int, mode: graph.Mode):
    config = project.config
    return subs.compose(
        lyrics,
        song=config.song,
        overlay=config.overlay_text,
        fade_ms=config.lyrics.fade_ms,
        duration_ms=duration_ms,
        include_lyrics=mode != "preview",
    )


def _render(project_dir: Path | None, mode: graph.Mode, label: str) -> Path:
    require_tools()
    project = _load_project(project_dir)
    analysis = analyze(project, mode)
    _print_issues(analysis.issues)
    if not analysis.ok:
        raise typer.Exit(1)
    assert analysis.lyrics is not None and analysis.duration_s is not None

    config = project.config
    script = _compose(project, analysis.lyrics, round(analysis.duration_s * 1000), mode)
    project.work_dir.mkdir(parents=True, exist_ok=True)
    subtitles_path = project.work_dir / f"{mode}.ass"
    script.save(str(subtitles_path), encoding="utf-8", format_="ass")

    spec = graph.RenderSpec(
        mode=mode,
        size=config.video.size,
        fps=config.video.fps,
        duration_s=analysis.duration_s,
        audio=project.audio_path.absolute(),
        subtitles=subtitles_path.absolute(),
        fontsdir=fonts.prepare_fontsdir(analysis.font_files, cache_dir() / "fontsets"),
        background=project.background_path.absolute(),
        fit=config.video.fit,
        scale_flags=config.video.scale_flags,
        pad_color=config.video.pad_color,
        crf=config.video.crf,
        preset=config.video.preset,
    )
    output = {
        "final": project.main_output,
        "preview": project.preview_bg_output,
        "overlay": project.overlay_output,
    }[mode]

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(label, total=1.0)
        run(
            graph.build_args(spec),
            output,
            total_s=analysis.duration_s,
            on_progress=lambda fraction: progress.update(task, completed=fraction),
        )
    console.print(f"書き出しました: {output}", markup=False)
    if windows_path := to_windows_path(output):
        console.print(f"  Windows: {windows_path}", markup=False)
    return output


def _print_scaffold(result: ScaffoldResult, root: Path) -> None:
    for path in result.created:
        console.print(f"  作成: {path.relative_to(root)}", markup=False)
    for path in result.skipped:
        console.print(f"  既にあるので変更なし: {path.relative_to(root)}", markup=False)


_NEXT_STEPS = """次にやること（詳しくは docs/workflow.md）:
  1. utavideo.toml の audio.file / video.background / song.artist を埋める
  2. utavideo preview-bg → Aegisub で src/lyrics.ass と build/preview/bg.mp4 を開いて歌詞を入れる
  3. utavideo check → utavideo build → utavideo release"""


@app.command()
@_handle_errors
def new(
    title: Annotated[str, typer.Argument(help="曲名")],
    root: Annotated[Path, typer.Option(help="曲フォルダを作る場所")] = Path("."),
    day: Annotated[str | None, typer.Option("--date", help="YYYYMMDD。省略時は今日")] = None,
) -> None:
    """新しい曲フォルダを雛形から作る。"""
    try:
        created_on = datetime.strptime(day, "%Y%m%d").date() if day else date.today()
    except ValueError:
        _fail(f"--date は YYYYMMDD で指定してください: {day}")
    dest = root / project_dir_name(title, created_on)
    if dest.exists():
        _fail(f"既にあります: {dest}（既存のフォルダに追加するなら utavideo init）")
    result = scaffold(dest, title)
    console.print(f"作成しました: {dest}", markup=False)
    _print_scaffold(result, dest)
    console.print(_NEXT_STEPS, markup=False)


@app.command()
@_handle_errors
def init(
    directory: Annotated[Path, typer.Argument(help="既存の曲フォルダ")] = Path("."),
    title: Annotated[str | None, typer.Option(help="曲名。省略時はフォルダ名から日付を除いたもの")] = None,
) -> None:
    """既存の曲フォルダに utavideo のファイルを追加する（既存ファイルは移動も上書きもしない）。"""
    if not directory.is_dir():
        _fail(f"ディレクトリがありません: {directory}")
    root = directory.absolute()
    result = scaffold(root, title or title_from_dir_name(root.name))
    console.print(f"初期化しました: {root}", markup=False)
    _print_scaffold(result, root)
    console.print(_NEXT_STEPS, markup=False)


@app.command()
@_handle_errors
def check(project_dir: ProjectOption = None) -> None:
    """設定・素材・歌詞・フォントを検査する。"""
    require_tools()
    project = _load_project(project_dir)
    analysis = analyze(project, "final")
    config = project.config

    console.print(f"曲フォルダ: {project.root}", markup=False)
    console.print(f"  曲名: {config.song.title} / {config.song.artist or '（artist 未設定）'}", markup=False)
    if analysis.duration_s is not None:
        console.print(f"  音声: {project.audio_path.name}（{analysis.duration_s:.2f} 秒）", markup=False)
    if analysis.lyrics is not None:
        console.print(f"  歌詞: {len(subs.dialogues(analysis.lyrics))} 行", markup=False)
    for file in analysis.font_files:
        console.print(f"  フォント: {file}", markup=False)
    if version := project.version:
        console.print(f"  release 先: {project.release_path(version)}", markup=False)
    else:
        message = "audio.file のファイル名に vX.Y が無いので、release では --version が必要です"
        analysis.issues.append(subs.Issue("warning", message))
    if not config.song.artist:
        analysis.issues.append(subs.Issue("warning", "song.artist が空です"))

    _print_issues(analysis.issues)
    if not analysis.ok:
        raise typer.Exit(1)
    console.print("[green]問題ありません[/]")


@app.command("preview-bg")
@_handle_errors
def preview_bg(project_dir: ProjectOption = None) -> None:
    """歌詞以外（背景・曲名表示・音声）を合成した、Aegisub 用のプレビュー動画を書き出す。"""
    _render(project_dir, "preview", "preview-bg")


@app.command()
@_handle_errors
def build(project_dir: ProjectOption = None) -> None:
    """本番の動画を build/main.mp4 に書き出す。"""
    _render(project_dir, "final", "build")


@app.command()
@_handle_errors
def overlay(project_dir: ProjectOption = None) -> None:
    """歌詞と曲名表示を透過 ProRes 4444（build/overlay.mov）で書き出す。動画編集ソフトで重ねる用。"""
    _render(project_dir, "overlay", "overlay")


@app.command()
@_handle_errors
def release(
    project_dir: ProjectOption = None,
    version: Annotated[
        str | None, typer.Option("--version", help="例: v1.0。省略時は audio.file のファイル名から")
    ] = None,
    allow_stale: Annotated[
        bool, typer.Option(help="build/main.mp4 より新しい入力があってもコピーする")
    ] = False,
) -> None:
    """build/main.mp4 を release/<曲名> <バージョン>.mp4 にコピーする。"""
    project = _load_project(project_dir)
    source = project.main_output
    if not source.is_file():
        _fail("build/main.mp4 がありません。先に utavideo build を実行してください")

    version = version or project.version
    if version is None:
        _fail("audio.file のファイル名に vX.Y が無いので --version で指定してください")
    if not re.fullmatch(r"v\d+(\.\d+)*", version):
        _fail(f"バージョンは v1.0 のような形式で指定してください: {version}")

    inputs = [project.config_path, project.audio_path, project.background_path, project.lyrics_path]
    built_at = source.stat().st_mtime
    stale = [p for p in inputs if p.is_file() and p.stat().st_mtime > built_at]
    if stale and not allow_stale:
        names = ", ".join(p.name for p in stale)
        _fail(
            f"build/main.mp4 より新しい入力があります（{names}）。"
            "build し直すか --allow-stale を付けてください"
        )

    dest = project.release_path(version)
    if dest.exists():
        _fail(f"既にあります: {dest}（上書きはしません）")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = partial_path(dest)
    shutil.copy2(source, tmp)
    tmp.replace(dest)
    console.print(f"コピーしました: {dest}", markup=False)
