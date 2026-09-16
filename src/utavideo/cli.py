"""utavideo コマンド。"""

import filecmp
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

from utavideo import description, fonts, graph, layout, subs
from utavideo.config import cache_dir, load_user_config
from utavideo.errors import UtavideoError
from utavideo.ffmpeg import partial_path, probe_audio, replace_partial, require_tools, run
from utavideo.project import (
    VERSION_PATTERN,
    Project,
    ScaffoldResult,
    find_project_root,
    next_revision,
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
ArtistOption = Annotated[str, typer.Option(help="アーティスト名（utavideo.toml の song.artist）")]


def _handle_errors[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        # OSError: 権限が無い・パスが長すぎる等。traceback を出さずにメッセージだけにする
        except (UtavideoError, OSError) as e:
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


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = partial_path(path)
    tmp.write_text(text, encoding="utf-8", newline="\n")
    replace_partial(tmp, path)


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

    duration_s: float | None = None
    if project.audio_path.is_file():
        audio = probe_audio(project.audio_path)
        duration_s = audio.duration_s
        if not audio.has_sound:
            issues.append(subs.Issue("error", f"audio.file に音声が入っていません: {project.audio_path}"))
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
  1. utavideo.toml の audio.file / video.background を合わせ、song を確認する
  2. utavideo preview-bg → Aegisub で src/lyrics.ass と build/preview/bg.mp4 を開いて歌詞を入れる
  3. utavideo check → utavideo build → utavideo release"""


@app.command()
@_handle_errors
def new(
    title: Annotated[str, typer.Argument(help="曲名")],
    artist: ArtistOption = "",
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
    result = scaffold(dest, title, artist, load_user_config().defaults)
    console.print(f"作成しました: {dest}", markup=False)
    _print_scaffold(result, dest)
    console.print(_NEXT_STEPS, markup=False)


@app.command()
@_handle_errors
def init(
    directory: Annotated[Path, typer.Argument(help="既存の曲フォルダ")] = Path("."),
    title: Annotated[str | None, typer.Option(help="曲名。省略時はフォルダ名から日付を除いたもの")] = None,
    artist: ArtistOption = "",
) -> None:
    """既存の曲フォルダに utavideo のファイルを追加する（既存ファイルは移動も上書きもしない）。"""
    if not directory.is_dir():
        _fail(f"ディレクトリがありません: {directory}")
    root = directory.absolute()
    result = scaffold(root, title or title_from_dir_name(root.name), artist, load_user_config().defaults)
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
    issues = list(analysis.issues)
    if version := project.version:
        dest = project.release_path(version, next_revision(project.released(version)))
        console.print(f"  release 先: {dest}", markup=False)
    else:
        message = "audio.file のファイル名に vX.Y が無いので、release では --version が必要です"
        issues.append(subs.Issue("warning", message))
    if not config.song.artist:
        issues.append(subs.Issue("warning", "song.artist が空です"))
    if config.description is not None:
        issues += description.lint(project, load_user_config().description)

    _print_issues(issues)
    if any(issue.level == "error" for issue in issues):
        raise typer.Exit(1)
    warnings = sum(issue.level == "warning" for issue in issues)
    if warnings:
        console.print(f"[yellow]エラーはありません（警告 {warnings} 件）[/]")
    else:
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


@app.command("description")
@_handle_errors
def description_command(project_dir: ProjectOption = None) -> None:
    """utavideo.toml のクレジット・素材から、タイトルと概要欄を build/ に書き出す。"""
    project = _load_project(project_dir)
    fmt = load_user_config().description
    title = description.render_title(project.config, fmt)
    body = description.render_body(project.config, fmt)
    if project.config.description is not None:
        _print_issues(description.lint(project, fmt))
    _write_text(project.title_output, title)
    _write_text(project.description_output, body)
    console.print(title, markup=False)
    console.print()
    console.print(body, markup=False, end="")
    for path in (project.title_output, project.description_output):
        console.print(f"書き出しました: {path}", markup=False)


def _description_text(project: Project) -> str | None:
    """release に置く概要欄。[description] が無い曲では None。"""
    if project.config.description is None:
        return None
    fmt = load_user_config().description
    title = description.render_title(project.config, fmt)
    return f"{title}\n\n{description.render_body(project.config, fmt)}"


def _rewrite_description(project: Project, version: str) -> None:
    """公開済みの概要欄を今の設定で書き直す。release/ のファイルを上書きする唯一の場所。"""
    text = _description_text(project)
    if text is None:
        _fail("utavideo.toml に [description] がありません")
    released = project.released(version)
    if not released:
        _fail(f"{version} で公開した動画が release/ にありません")
    _, latest = max(released, key=lambda item: item[0])
    dest = latest.with_suffix(".txt")
    if dest.is_file() and dest.read_text(encoding="utf-8") == text:
        console.print(f"変わっていません: {dest}", markup=False)
        return
    _write_text(dest, text)
    console.print(f"書き直しました: {dest}", markup=False)


@app.command()
@_handle_errors
def release(
    project_dir: ProjectOption = None,
    version: Annotated[
        str | None,
        typer.Option("--version", help="音源のバージョン。例: v1.0。省略時は audio.file のファイル名から"),
    ] = None,
    allow_stale: Annotated[
        bool, typer.Option(help="build/main.mp4 より新しい入力があってもコピーする")
    ] = False,
    description_only: Annotated[
        bool,
        typer.Option("--description-only", help="動画はコピーせず、公開済みの概要欄を書き直す"),
    ] = False,
) -> None:
    """build/main.mp4 を release/<曲名> <音源のバージョン>.<何本目か>.mp4 にコピーする。"""
    project = _load_project(project_dir)
    source = project.main_output
    if not source.is_file() and not description_only:
        _fail("build/main.mp4 がありません。先に utavideo build を実行してください")

    version = version or project.version
    if version is None:
        _fail("audio.file のファイル名に vX.Y が無いので --version で指定してください")
    if not re.fullmatch(VERSION_PATTERN, version, re.IGNORECASE):
        _fail(f"音源のバージョンは v1.0 のような vX.Y の形で指定してください: {version}")
    version = version.lower()

    if description_only:
        _rewrite_description(project, version)
        return

    inputs = [project.config_path, project.audio_path, project.background_path, project.lyrics_path]
    built_at = source.stat().st_mtime
    stale = [p for p in inputs if p.is_file() and p.stat().st_mtime > built_at]
    if stale and not allow_stale:
        names = ", ".join(p.name for p in stale)
        _fail(
            f"build/main.mp4 より新しい入力があります（{names}）。"
            "build し直すか --allow-stale を付けてください"
        )

    # 書き出し直しただけの動画を別の番号で公開しないよう、公開済みのものと中身を比べる
    # （同じ入力からの build はバイト単位で一致する。docs/verification/20260916-release-revision.md）
    released = project.released(version)
    same = next((p for _, p in released if filecmp.cmp(source, p, shallow=False)), None)
    if same is not None:
        _fail(f"同じ内容が既にあります: {same}（コピーしません）")

    dest = project.release_path(version, next_revision(released))
    # 書式を後で変えても公開したときの文章が残るよう、概要欄も一緒に置く
    text_dest = dest.with_suffix(".txt")
    text = _description_text(project)
    for path in [dest, *([text_dest] if text is not None else [])]:
        if path.exists():
            _fail(f"既にあります: {path}（上書きはしません）")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 片方だけ残ると再実行が「既にあります」で止まるので、.txt を先に書き、動画のコピーに失敗したら消す
    if text is not None:
        _write_text(text_dest, text)
    try:
        tmp = partial_path(dest)
        shutil.copy2(source, tmp)
        replace_partial(tmp, dest)
    except BaseException:
        if text is not None:
            text_dest.unlink(missing_ok=True)
        raise
    console.print(f"コピーしました: {dest}", markup=False)
    if text is not None:
        console.print(f"書き出しました: {text_dest}", markup=False)
