"""utavideo コマンド。"""

import filecmp
import functools
import os
import re
import shutil
import sys
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import pysubs2
import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn

from utavideo import description, fonts, graph, layout, shorts, subs, vertical
from utavideo.config import (
    PROJECT_CONFIG_NAME,
    Layout,
    OverlayText,
    Short,
    Thumbnail,
    cache_dir,
    load_user_config,
)
from utavideo.errors import UtavideoError
from utavideo.ffmpeg import (
    FFmpegError,
    NoOutputError,
    partial_path,
    probe_audio,
    probe_duration,
    replace_partial,
    require_tools,
    run,
)
from utavideo.names import has_date_prefix, slug_error, slug_from_dir_name
from utavideo.project import (
    SHORTS_EXAMPLE,
    THUMBNAIL_EXAMPLE,
    THUMBNAIL_TEMPLATE_PATH,
    VERSION_PATTERN,
    Project,
    ScaffoldResult,
    find_project_root,
    next_revision,
    require_usable_slug,
    scaffold,
    to_windows_path,
)
from utavideo.timecode import format_time

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
TitleOption = Annotated[
    str | None, typer.Option(help="曲名（utavideo.toml の song.title）。省略時は端末なら聞く")
]
ArtistOption = Annotated[
    str | None, typer.Option(help="アーティスト名（utavideo.toml の song.artist）。省略時は端末なら聞く")
]
SlugOption = Annotated[
    str | None,
    typer.Option(help="ファイル名に使う識別子（utavideo.toml の song.slug）。省略時はフォルダ名"),
]


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


def analyze(project: Project, mode: graph.Mode, search: "_FontSearch | None" = None) -> Analysis:
    """書き出しに必要なものが揃っているかを調べる。preview では歌詞の行の中身は問わない。"""
    config = project.config
    issues, duration_s = _audio_issues(project)
    if not project.lyrics_path.is_file():
        issues.append(subs.Issue("error", f"lyrics.file のファイルがありません: {project.lyrics_path}"))
    if mode != "overlay":
        issues += _background_issues(project)

    lyrics = subs.load(project.lyrics_path) if project.lyrics_path.is_file() else None
    if lyrics is None or duration_s is None:
        return Analysis(issues, duration_s, lyrics, ())

    duration_ms = round(duration_s * 1000)
    target = lyrics if mode != "preview" else subs.without_events(lyrics)
    issues += subs.lint(target, size=config.video.size, duration_ms=duration_ms, overlay=config.overlay_text)

    script = _compose(project, lyrics, duration_ms, mode)
    font_issues, font_files = _check_fonts(script, search or _FontSearch.load())
    return Analysis(issues + font_issues, duration_s, lyrics, font_files)


def _audio_issues(project: Project) -> tuple[list[subs.Issue], float | None]:
    """音源のファイルと音声の検査と、音源の長さ（秒。読めなければ None）。"""
    path = project.audio_path
    if not path.is_file():
        return [subs.Issue("error", f"audio.file のファイルがありません: {path}")], None
    audio = probe_audio(path)
    if not audio.has_sound:
        return [subs.Issue("error", f"audio.file に音声が入っていません: {path}")], audio.duration_s
    return [], audio.duration_s


def _background_issues(project: Project) -> list[subs.Issue]:
    path = project.background_path
    if not path.is_file():
        return [subs.Issue("error", f"video.background のファイルがありません: {path}")]
    ext = path.suffix.lower()
    if ext not in graph.IMAGE_EXTS | graph.ANIMATED_EXTS:
        return [subs.Issue("error", f"video.background の形式に対応していません: {ext}")]
    return []


@dataclass(frozen=True)
class _FontSearch:
    dirs: list[Path]
    index: fonts.FontIndex

    @classmethod
    def load(cls) -> "_FontSearch":
        dirs = load_user_config().font_dirs
        cache_file = cache_dir() / "fonts.json"
        if not cache_file.exists():
            console.print("フォント一覧を作成しています（初回のみ時間がかかります）…")
        return cls(dirs, fonts.load_index(dirs, cache_file))


def _check_fonts(
    script: pysubs2.SSAFile, search: _FontSearch, *, overflows: bool = True
) -> tuple[list[subs.Issue], tuple[Path, ...]]:
    """使っているフォントを探し、見つからないフォントのエラーと、はみ出しそうな行の警告を返す。"""
    resolution = fonts.resolve(search.index, subs.used_fonts(script))
    issues: list[subs.Issue] = []
    for name in resolution.missing:
        searched = ", ".join(map(str, search.dirs)) or "（なし）"
        issues.append(subs.Issue("error", f"フォント {name!r} が見つかりません（探した場所: {searched}）"))
    if overflows:
        issues += layout.overflows(script, search.index.lookup)
    return issues, resolution.files


def _compose(
    project: Project,
    lyrics: pysubs2.SSAFile,
    duration_ms: int,
    mode: graph.Mode,
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
        no_fade_style_prefix=vertical.VERTICAL_STYLE_PREFIX if no_vertical_fade else None,
    )


def _frame_script(project: Project, lyrics: pysubs2.SSAFile, duration_ms: int) -> pysubs2.SSAFile:
    """blur の真ん中に置く本編の映像に描く .ass。

    build/main.mp4 と同じ画面にする。曲名表示だけ vertical.overlay_text で決まる。
    """
    return _compose(project, lyrics, duration_ms, "final", overlay=project.vertical_overlay_text)


def _render(project_dir: Path | None, mode: graph.Mode, label: str) -> Path:
    require_tools()
    project = _load_project(project_dir)
    analysis = analyze(project, mode)
    _print_issues(analysis.issues)
    if not analysis.ok:
        raise typer.Exit(1)
    assert analysis.lyrics is not None and analysis.duration_s is not None

    script = _compose(project, analysis.lyrics, round(analysis.duration_s * 1000), mode)
    output = {
        "final": project.main_output,
        "preview": project.preview_bg_output,
        "overlay": project.overlay_output,
    }[mode]
    video = project.config.video
    target = _VideoTarget(mode, video.size, video.focus, project.work_dir / f"{mode}.ass", output, label)
    return _write_video(project, script, target, analysis.duration_s, analysis.font_files)


@dataclass(frozen=True)
class _Frame:
    """blur の画面で、ぼかした帯の上に置く本編の映像。"""

    script: pysubs2.SSAFile  # 本編の合成したスクリプト
    subtitles_path: Path  # 描画に使った .ass を書く場所


@dataclass(frozen=True)
class _VideoTarget:
    """書き出す動画ごとに違うもの。ほかの設定（fps・fit・crf など）は [video] を使う。"""

    mode: graph.Mode
    size: tuple[int, int]
    focus: tuple[float, float]
    subtitles_path: Path  # 描画に使った .ass を書く場所
    output: Path
    label: str
    clip: graph.Clip | None = None  # 切り出す区間（None なら曲全体）
    frame: _Frame | None = None  # None なら背景を size に合わせる画面（reframe）


def _write_video(
    project: Project,
    script: pysubs2.SSAFile,
    target: _VideoTarget,
    duration_s: float,
    font_files: tuple[Path, ...],
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
    )

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
    console.print(f"書き出しました: {output}", markup=False)
    if windows_path := to_windows_path(output):
        console.print(f"  Windows: {windows_path}", markup=False)
    return output


def _save_script(script: pysubs2.SSAFile, path: Path) -> None:
    """描画に使う .ass を書く。ほかの出力と同じく .partial に書いてから名前を変える。"""
    _write_text(path, script.to_string("ass"))


def _print_scaffold(result: ScaffoldResult, root: Path) -> None:
    for path in result.created:
        console.print(f"  作成: {path.relative_to(root)}", markup=False)
    for path in result.skipped:
        console.print(f"  既にあるので変更なし: {path.relative_to(root)}", markup=False)


_NEXT_STEPS = """次にやること（詳しくは docs/workflow.md）:
  1. utavideo.toml の audio.file / video.background を合わせ、song を確認する
  2. utavideo preview-bg → Aegisub で src/lyrics.ass と build/preview/bg.mp4 を開いて歌詞を入れる
  3. utavideo check → utavideo build → utavideo release
  4. utavideo thumbnail --bg-only → Aegisub で src/thumbnail.ass を開いて文字を組む → utavideo thumbnail
  5. 縦型のショートを作るなら、utavideo.toml に [vertical]（画面の作り方 layout）を書く →
     utavideo vertical-ass → utavideo preview-bg --vertical → Aegisub で src/vertical.ass を組み、
     区間を置く → utavideo.toml に [[shorts]] → utavideo shorts"""


@app.command()
@_handle_errors
def new(
    path: Annotated[Path, typer.Argument(help="作る曲フォルダのパス（例: work/20260916-song）")],
    title: TitleOption = None,
    artist: ArtistOption = None,
    slug: SlugOption = None,
) -> None:
    """新しい曲フォルダを雛形から作る。フォルダ名はこのパスのまま（日付などは自分で付ける）。"""
    if path.exists():
        _fail(f"既にあります: {path}（既存のフォルダに追加するなら utavideo init）")
    # 作るのは utavideo なので、Windows で開けない名前のフォルダを作らない
    if reason := slug_error(path.name):
        _fail(f"フォルダ名に使えません（{reason}）: {path.name}")
    hint = None
    if not has_date_prefix(path.name):
        hint = (
            f"ヒント: フォルダ名を {date.today():%Y%m%d}-{path.name} のようにすると、"
            "日付順に並び、slug からは日付が外れます"
        )
    _scaffold(path, title, artist, slug, "作成しました", hint)


@app.command()
@_handle_errors
def init(
    directory: Annotated[Path, typer.Argument(help="既存の曲フォルダ")] = Path("."),
    title: TitleOption = None,
    artist: ArtistOption = None,
    slug: SlugOption = None,
) -> None:
    """既存の曲フォルダに utavideo のファイルを追加する（既存ファイルは移動も上書きもしない）。"""
    if not directory.is_dir():
        _fail(f"ディレクトリがありません: {directory}")
    _scaffold(directory.resolve(), title, artist, slug, "初期化しました")


def _scaffold(
    root: Path, title: str | None, artist: str | None, slug: str | None, done: str, hint: str | None = None
) -> None:
    resolved_slug = slug if slug is not None else _slug_from_dir(root)
    require_usable_slug(resolved_slug)
    # utavideo.toml があるときは書き換えないので、聞いても捨てることになる
    asks = not (root / PROJECT_CONFIG_NAME).is_file()
    if title is None:
        title = _ask("曲名", resolved_slug) if asks else resolved_slug
    if artist is None:
        artist = _ask("アーティスト名", "") if asks else ""
    result = scaffold(root, title, resolved_slug, artist, load_user_config().defaults)
    console.print(f"{done}: {root}", markup=False)
    if hint is not None:
        console.print(f"[yellow]{hint}[/]", markup=True, highlight=False)
    _print_scaffold(result, root)
    # 既にあった utavideo.toml は書き換えないので、サムネイルの雛形も作っていない
    if root / PROJECT_CONFIG_NAME in result.skipped and not _has_thumbnails(root):
        console.print(
            f"サムネイルを作るときは、utavideo.toml に次を書き足し、{THUMBNAIL_TEMPLATE_PATH} を用意します"
            "（src/lyrics.ass をコピーして Dialogue の行を消すと、スタイルと PlayRes をそのまま使えます）:\n"
            + THUMBNAIL_EXAMPLE,
            markup=False,
        )
    console.print(_NEXT_STEPS, markup=False)


def _has_thumbnails(root: Path) -> bool:
    try:
        return bool(Project.load(root).config.thumbnails)
    except UtavideoError:  # 読めない utavideo.toml でも、案内を出すだけなので止めない
        return False


def _slug_from_dir(root: Path) -> str:
    """フォルダ名から slug を決める。使えない名前なら、端末では聞き直す（端末でなければエラー）。"""
    value = slug_from_dir_name(root.resolve().name)
    source = "フォルダ名"
    while (reason := slug_error(value)) is not None and _interactive():
        err_console.print(f"{source}は名前に使えません（{reason}）: {value}", markup=False)
        value = typer.prompt("ファイル名に使う識別子（slug）")
        source = "入力した名前"
    return value


def _ask(label: str, default: str) -> str:
    """端末なら聞く。パイプや CI からは既定値をそのまま使う。"""
    return typer.prompt(label, default=default) if _interactive() else default


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


@app.command()
@_handle_errors
def check(project_dir: ProjectOption = None) -> None:
    """設定・素材・歌詞・フォントを検査する。"""
    require_tools()
    project = _load_project(project_dir)
    # フォントの一覧は、歌詞とサムネイルの検査で1回だけ読む
    search = _FontSearch.load()
    analysis = analyze(project, "final", search)
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
    if not project.slug.isascii():
        message = f"song.slug に ASCII 以外の文字が入っています（{project.slug}）"
        issues.append(subs.Issue("warning", message))
    if config.description is not None:
        issues += description.lint(project, load_user_config().description)
    for thumb in config.thumbnails:
        size = project.thumbnail_size(thumb)
        console.print(f"  サムネイル: {thumb.name}（{size[0]}x{size[1]}、{thumb.file}）", markup=False)
    # 背景のファイル自体の検査は analyze で済んでいる
    issues += analyze_thumbnails(project, config.thumbnails, bg_only=False, search=search).issues
    if analysis.lyrics is not None:
        issues += shorts.main_lyrics_issues(analysis.lyrics)
    # ショートを作らない曲では縦用 .ass を見ない（vertical-ass を試しただけの曲で止めない）
    if config.shorts:
        size = config.vertical.size
        console.print(f"  縦用 .ass: {config.vertical.lyrics}（{size[0]}x{size[1]}）", markup=False)
        console.print(f"  ショート: {', '.join(s.name for s in config.shorts)}", markup=False)
        found = analyze_shorts(
            project, search, analysis.duration_s, analysis.lyrics, config.shorts, report_unused=True
        )
        issues += found.issues

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
def preview_bg(
    project_dir: ProjectOption = None,
    vertical_: Annotated[
        bool,
        typer.Option(
            "--vertical",
            help="縦型のショートの下敷きを build/preview/vertical-bg.mp4 に書き出す（縦用 .ass を使う）",
        ),
    ] = False,
) -> None:
    """歌詞以外（背景・曲名表示・音声）を合成した、Aegisub 用のプレビュー動画を書き出す。"""
    if vertical_:
        _render_vertical_preview(project_dir)
    else:
        _render(project_dir, "preview", "preview-bg")


def _vertical_inputs(project: Project, search: _FontSearch, *, draws_main: bool) -> Analysis:
    """縦の書き出しに要るものの検査と、音源の長さ・本編の .ass（無ければ None）。

    draws_main は本編の映像も描くとき（blur の真ん中、wide の版）で、本編の .ass とフォントも
    build と同じ条件で検査する。描かないなら、本編の .ass は突き合わせと LayoutRes にだけ使い、
    フォントは縦用 .ass のものだけでよい（文字が潰れる LayoutRes は本編の書き出しと同じく止める）。
    """
    if draws_main:
        return analyze(project, "final", search)
    issues, duration_s = _audio_issues(project)
    issues += _background_issues(project)
    lyrics = subs.load(project.lyrics_path) if project.lyrics_path.is_file() else None
    if lyrics is not None:
        issues += subs.layout_res_issues(lyrics)
    return Analysis(issues, duration_s, lyrics, ())


def _render_vertical_preview(project_dir: Path | None) -> None:
    require_tools()
    project = _load_project(project_dir)
    layouts = project.vertical_layouts
    # 下敷きは、実際に使う画面に合わせる。blur が1本でもあれば、真ん中に本編の映像を置く
    layout_: Layout = "blur" if "blur" in layouts else "reframe"
    search = _FontSearch.load()
    inputs = _vertical_inputs(project, search, draws_main=layout_ == "blur")
    issues, duration_s = inputs.issues, inputs.duration_s
    # 縦用 .ass のファイル全体の検査は、check・shorts と同じ layouts で行う（食い違わせない）
    checked = analyze_vertical(project, search, layouts=layouts)
    issues += checked.issues
    _print_issues(issues)
    if any(issue.level == "error" for issue in issues):
        raise typer.Exit(1)
    assert checked.script is not None and duration_s is not None

    duration_ms = round(duration_s * 1000)
    overlay = project.vertical_script_overlay_text([layout_])
    script = _compose(project, checked.script, duration_ms, "preview", no_vertical_fade=True, overlay=overlay)
    frame, font_files = None, checked.font_files
    if layout_ == "blur":
        # 下敷きも完成図と同じ画面にする。本編の歌詞は真ん中の映像に入れ、縦用 .ass の行は入れない
        assert inputs.lyrics is not None
        frame_script = _frame_script(project, inputs.lyrics, duration_ms)
        frame = _Frame(frame_script, project.work_dir / "vertical-preview-frame.ass")
        font_files += inputs.font_files
    target = _VideoTarget(
        "preview",
        project.config.vertical.size,
        project.vertical_focus,
        project.work_dir / "vertical-preview.ass",
        project.vertical_preview_bg_output,
        "preview-bg --vertical",
        frame=frame,
    )
    _write_video(project, script, target, duration_s, font_files)


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
) -> None:
    """build/main.mp4 を release/<slug>-<音源のバージョン>.<何本目か>.mp4 にコピーする。"""
    project = _load_project(project_dir)
    source = project.main_output
    if not source.is_file():
        _fail("build/main.mp4 がありません。先に utavideo build を実行してください")

    version = version or project.version
    if version is None:
        _fail("audio.file のファイル名に vX.Y が無いので --version で指定してください")
    if not re.fullmatch(VERSION_PATTERN, version, re.IGNORECASE):
        _fail(f"音源のバージョンは v1.0 のような vX.Y の形で指定してください: {version}")
    version = version.lower()

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
    if dest.exists():
        _fail(f"既にあります: {dest}（上書きはしません）")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = partial_path(dest)
    shutil.copy2(source, tmp)
    replace_partial(tmp, dest)
    console.print(f"コピーしました: {dest}", markup=False)


@dataclass(frozen=True)
class VerticalAnalysis:
    issues: list[subs.Issue]
    script: pysubs2.SSAFile | None  # 読めなかったときは None
    font_files: tuple[Path, ...]


def analyze_vertical(
    project: Project, search: _FontSearch, *, layouts: Collection[Layout]
) -> VerticalAnalysis:
    """縦用 .ass のファイル全体の検査（PlayRes・LayoutRes・スタイル・フォント）と、blur の大きさ。

    layouts は、この縦用 .ass から描く画面の作り方（曲名表示のスタイルが要るかが変わる）。
    区間の外の行は書き出しに使わないので、行ごとの検査（はみ出しを含む）はここでは行わない。
    """
    sizing = _blur_frame_issues(project) if "blur" in layouts else []
    path = project.vertical_lyrics_path
    if not path.is_file():
        message = (
            f"縦用 .ass（vertical.lyrics）のファイルがありません: {path}（utavideo vertical-ass で作れます）"
        )
        return VerticalAnalysis([*sizing, subs.Issue("error", message)], None, ())
    try:
        script = subs.load(path)
    except subs.SubtitleError as e:
        return VerticalAnalysis([*sizing, subs.Issue("error", f"縦用 .ass: {e}")], None, ())
    config = project.config
    overlay = project.vertical_script_overlay_text(layouts)
    issues = subs.lint_vertical(script, size=config.vertical.size, overlay=overlay)
    # 曲名表示のフォントも探すよう、書き出しと同じく曲名表示の行を足してから調べる
    composed = _compose(project, script, 0, "final", no_vertical_fade=True, overlay=overlay)
    font_issues, font_files = _check_fonts(composed, search, overflows=False)
    return VerticalAnalysis(sizing + subs.prefixed(issues + font_issues, "縦用 .ass: "), script, font_files)


def _blur_frame_issues(project: Project) -> list[subs.Issue]:
    """blur の真ん中に置く本編の映像が、縦の画面に収まるか。

    video.size が vertical.size より縦長だと、幅いっぱいに縮めた本編が縦からはみ出し、
    黙って上下を切られる（frame_y の 0〜1 が「上端から下端まで」を指さなくなる）。
    """
    video = project.config.video
    width, height = project.config.vertical.size
    frame = graph.frame_height(video.size, width)
    if frame <= height:
        return []
    message = (
        f"blur の画面を作れません: video.size（{video.size[0]}x{video.size[1]}）が "
        f"vertical.size（{width}x{height}）より縦長なので、縦の幅に縮めた本編の映像"
        f"（{width}x{frame}）が縦の画面に収まりません"
        '（vertical.size を高くするか、vertical.layout = "reframe" にします）'
    )
    return [subs.Issue("error", message)]


@dataclass(frozen=True)
class ShortsAnalysis:
    issues: list[subs.Issue]
    script: pysubs2.SSAFile | None  # 縦用 .ass（読めなかったときは None）
    sections: dict[str, shorts.Section]  # 検査を通った区間（ショートの名前ごと）
    font_files: tuple[Path, ...]


def analyze_shorts(
    project: Project,
    search: _FontSearch,
    duration_s: float | None,
    lyrics: pysubs2.SSAFile | None,
    targets: tuple[Short, ...],
    *,
    report_unused: bool,
) -> ShortsAnalysis:
    """targets のショートの検査。縦用 .ass のファイル全体と、区間の行、区間に入る行。

    duration_s は音源の長さ（読めなければ None で、長さとの比較と行の検査をしない）。
    lyrics は本編の .ass（読めなければ None で、本編との突き合わせをしない）。
    report_unused は、どの name にも合わない区間の行を警告するか。
    """
    checked = analyze_vertical(project, search, layouts=[project.short_layout(s) for s in targets])
    if checked.script is None:
        return ShortsAnalysis(checked.issues, None, {}, checked.font_files)
    script = checked.script
    config = project.config
    duration_ms = None if duration_s is None else round(duration_s * 1000)
    found = shorts.check_sections(
        script, [s.name for s in targets], duration_ms=duration_ms, report_unused=report_unused
    )
    issues = checked.issues + found.issues
    sections = {section.name: section for section in found.sections}
    # blur の区間では、縦用 .ass に歌詞を置かない。歌詞についての検査は本編の .ass で行う
    edge_lines: dict[Layout, list[pysubs2.SSAEvent]] = {
        "reframe": shorts.lyric_lines(script),
        "blur": [] if lyrics is None else shorts.lyric_lines(lyrics),
    }
    by_layout: dict[Layout, list[shorts.Section]] = {}
    for short in targets:
        if (section := sections.get(short.name)) is None:
            continue
        layout_ = project.short_layout(short)
        by_layout.setdefault(layout_, []).append(section)
        found_issues = shorts.edge_issues(edge_lines[layout_], section)
        # 書き出しの前に必ず通す検査。区間が音源より後ろだと、ffmpeg は音声の無い動画を書いてしまう
        found_issues += shorts.render_issues(
            section,
            fps=config.video.fps,
            duration_ms=duration_ms,
            audio_fade_ms=config.vertical.audio_fade_ms,
            wide=short.wide,
        )
        issues += subs.prefixed(found_issues, f"ショート {short.name}: ")
    if lyrics is not None and (reframed := by_layout.get("reframe")):
        matched = shorts.match_lyrics(lyrics, script, reframed)
        issues += subs.prefixed(matched, "本編との突き合わせ: ")
    if duration_ms is not None:
        issues += subs.prefixed(_vertical_line_issues(script, by_layout, search, duration_ms), "縦用 .ass: ")
    return ShortsAnalysis(issues, script, sections, checked.font_files)


def _vertical_line_issues(
    script: pysubs2.SSAFile,
    by_layout: dict[Layout, list[shorts.Section]],
    search: _FontSearch,
    duration_ms: int,
) -> list[subs.Issue]:
    """区間に入る、描く行の警告。区間の外の行（本編の写し）は、本編と同じ警告を二重に出さない。

    描く行は画面の作り方で変わる（blur では帯の文字だけ）ので、まとめてから1回だけ検査する。
    そうしないと、reframe と blur の両方の区間に入る行の警告が2回出る。
    はみ出しは blur でも見る。帯の文字こそ vertical.size の幅に収まるか確かめたい行のため。
    """
    drawn = subs.without_events(script)
    drawn.events = [
        event
        for event in subs.dialogues(script)
        if any(shorts.draws(event, group, vertical_only=name == "blur") for name, group in by_layout.items())
    ]
    return subs.lint_lines(drawn.events, duration_ms=duration_ms) + layout.overflows(
        drawn, search.index.lookup
    )


@app.command("shorts")
@_handle_errors
def shorts_command(
    project_dir: ProjectOption = None,
    name: Annotated[str | None, typer.Option("--name", help="[[shorts]] の name。省略時はすべて")] = None,
) -> None:
    """縦型の切り抜きショートを build/shorts/<name>.mp4 に書き出す。"""
    require_tools()
    project = _load_project(project_dir)
    selected = _select_named(project.config.shorts, name, table="[[shorts]]", example=SHORTS_EXAMPLE)
    search = _FontSearch.load()
    layouts: list[Layout] = [project.short_layout(short) for short in selected]
    any_blur, any_wide = "blur" in layouts, any(s.wide for s in selected)
    # wide は本編と同じ画面、blur は真ん中に本編の映像を置くので、どちらも本編の .ass を描く
    draws_main = any_blur or any_wide
    inputs = _vertical_inputs(project, search, draws_main=draws_main)
    issues, duration_s, lyrics = inputs.issues, inputs.duration_s, inputs.lyrics
    analysis = analyze_shorts(project, search, duration_s, lyrics, selected, report_unused=name is None)
    issues += analysis.issues
    _print_issues(issues)
    if any(issue.level == "error" for issue in issues):
        raise typer.Exit(1)
    assert analysis.script is not None and duration_s is not None

    config = project.config
    fps = config.video.fps
    duration_ms = round(duration_s * 1000)
    # 本編の .ass はどのショートでも同じなので、合成は1回だけ（曲名表示の設定が wide と blur で違う）
    wide_script = frame_script = None
    if draws_main:
        assert lyrics is not None
        if any_wide:
            wide_script = _compose(project, lyrics, duration_ms, "final")
        if any_blur:
            frame_script = _frame_script(project, lyrics, duration_ms)
    for short, layout_ in zip(selected, layouts, strict=True):
        section = analysis.sections[short.name]
        blur = layout_ == "blur"
        clip = graph.Clip(*shorts.clip_frames(section, fps), config.vertical.audio_fade_ms)
        length_s = clip.duration_s(fps)
        # .ass の時刻はずらさない。区間の頭をまたぐ行の \\move・\\fad を本編と同じ状態で描くため
        in_section = shorts.lines_in_sections(analysis.script, [section], vertical_only=blur)
        overlay = project.vertical_script_overlay_text([layout_])
        script = _compose(project, in_section, duration_ms, "final", no_vertical_fade=True, overlay=overlay)
        frame, font_files = None, analysis.font_files
        if blur:
            assert frame_script is not None
            frame = _Frame(frame_script, project.short_work_ass(short, "frame"))
            font_files += inputs.font_files
        target = _VideoTarget(
            "final",
            config.vertical.size,
            project.short_focus(short),
            project.short_work_ass(short),
            project.short_output(short),
            f"shorts {short.name}",
            clip,
            frame,
        )
        _write_video(project, script, target, length_s, font_files)
        if not short.wide:
            continue
        assert wide_script is not None
        wide_target = _VideoTarget(
            "final",
            config.video.size,
            config.video.focus,
            project.short_work_ass(short, "wide"),
            project.short_output(short, wide=True),
            f"shorts {short.name}（wide）",
            clip,
        )
        # 本編と同じ .ass・同じ大きさで描くので、区間のコマは build/main.mp4 と一致する
        _write_video(project, wide_script, wide_target, length_s, inputs.font_files)


@app.command("vertical-ass")
@_handle_errors
def vertical_ass(project_dir: ProjectOption = None) -> None:
    """本編の歌詞 .ass から、縦型のショート用の .ass（vertical.lyrics）を作る。既にあれば止まる。"""
    project = _load_project(project_dir)
    dest = project.vertical_lyrics_path
    if dest.exists():
        _fail(f"既にあります: {dest}（上書きしません。作り直すときは、消してから実行します）")
    source = project.lyrics_path
    if not source.is_file():
        _fail(f"lyrics.file のファイルがありません: {source}")
    config = project.config
    size = config.vertical.size
    # blur では歌詞が本編の映像に入るので、縦用 .ass には写さない（Aegisub で二重に見えないように）。
    # reframe のショートが1本でもあれば、その区間では縦用 .ass の歌詞を描くので写す
    include_lyrics = Project.draws_vertical_lyrics(project.vertical_layouts)
    conversion = vertical.convert(
        subs.load(source),
        size=size,
        video_file=_path_from(dest.parent, project.vertical_preview_bg_output),
        source_dir=_path_from(dest.parent, source.parent),
        include_lyrics=include_lyrics,
    )
    _write_text(dest, conversion.script.to_string("ass"))

    console.print(f"作成しました: {dest}（{size[0]}x{size[1]}）", markup=False)
    if conversion.unconverted:
        lines = "\n".join(f"  {line}" for line in conversion.unconverted)
        _print_issues(
            [subs.Issue("warning", f"次の行の図形とベクターの \\clip は、座標を変換していません:\n{lines}")]
        )
    next_step = (
        "Aegisub で開き、スタイル Lyrics の大きさを上げてから、長い行を \\N で改行する"
        if include_lyrics
        # blur では歌詞を写していないので、直すのは帯の文字だけ
        else f"Aegisub で開き、帯に出す文字をスタイル {vertical.BAND_STYLE} で書く（歌詞は本編の映像に入る）"
    )
    console.print(f"次にやること（詳しくは docs/workflow.md）: {next_step}", markup=False)


def _path_from(start: Path, path: Path) -> str:
    """start から見た path。Aegisub の Video File: に書くので / で区切る。"""
    try:
        return Path(os.path.relpath(path, start)).as_posix()
    except ValueError:  # Windows でドライブが違うと相対パスにできない
        return path.absolute().as_posix()


@dataclass(frozen=True)
class ThumbnailAnalysis:
    issues: list[subs.Issue]
    font_files: dict[str, tuple[Path, ...]]


def analyze_thumbnails(
    project: Project, thumbnails: tuple[Thumbnail, ...], *, bg_only: bool, search: _FontSearch | None = None
) -> ThumbnailAnalysis:
    """サムネイルごとに書き出せるかを調べる。背景のファイル自体の検査（_background_issues）は呼び出し側で行う。

    bg_only では at だけを見る（.ass はまだ無くてよい）。
    """
    issues: list[subs.Issue] = []
    font_files: dict[str, tuple[Path, ...]] = {}
    background = project.background_path
    usable = not _background_issues(project)
    # GIF・動画の長さは、at を書いたサムネイルがあるときだけ、1回だけ調べる
    duration = None
    if usable and not graph.is_image(background) and any(t.at is not None for t in thumbnails):
        try:
            duration = probe_duration(background)
        except FFmpegError as e:
            # check で歌詞やフォントの検査結果まで出なくならないよう、止めずに検査の問題にする
            issues.append(subs.Issue("error", f"{e}（サムネイルの at を確かめられません）"))
            usable = False
    if not bg_only and search is None:
        search = _FontSearch.load()

    for thumb in thumbnails:
        found = background_time_issues(background, thumb.at, duration) if usable else []
        if not bg_only:
            assert search is not None
            found += _thumbnail_ass_issues(project, thumb, search, font_files)
        issues += subs.prefixed(found, f"サムネイル {thumb.name}: ")
    return ThumbnailAnalysis(issues, font_files)


def background_time_issues(background: Path, at: float | None, duration: float | None) -> list[subs.Issue]:
    """背景の at 秒のフレームを使えるか。duration は probe_duration の結果（画像では使わない）。"""
    if at is None:
        return []
    if graph.is_image(background):
        return [subs.Issue("error", "at は背景が GIF・動画のときだけ書けます（video.background は画像）")]
    if duration is None:
        return [subs.Issue("warning", "背景の長さを取得できないので、at が長さに収まるかを確かめられません")]
    if at >= duration:
        message = f"at（{format_time(at)}）が背景の長さ（{format_time(duration)}）以上です"
        return [subs.Issue("error", message)]
    return []


def _thumbnail_ass_issues(
    project: Project, thumb: Thumbnail, search: _FontSearch, font_files: dict[str, tuple[Path, ...]]
) -> list[subs.Issue]:
    path = project.thumbnail_file(thumb)
    if not path.is_file():
        return [subs.Issue("error", f"file のファイルがありません: {path}")]
    try:
        script = subs.load(path)
    except subs.SubtitleError as e:
        return [subs.Issue("error", str(e))]
    issues = subs.lint_still(script, size=project.thumbnail_size(thumb))
    font_issues, font_files[thumb.name] = _check_fonts(script, search)
    return issues + font_issues


def _select_named[T: Thumbnail | Short](
    items: tuple[T, ...], name: str | None, *, table: str, example: str
) -> tuple[T, ...]:
    """utavideo.toml の表から、--name で選んだものを取り出す。無ければ書き足し方を見せて止まる。"""
    if not items:
        _fail(f"utavideo.toml に {table} がありません。次を書き足してください:\n{example}")
    if name is None:
        return items
    found = tuple(item for item in items if item.name == name)
    if not found:
        names = ", ".join(item.name for item in items)
        _fail(f"{table} に name = {name!r} がありません（あるのは {names}）")
    return found


@app.command()
@_handle_errors
def thumbnail(
    project_dir: ProjectOption = None,
    name: Annotated[str | None, typer.Option("--name", help="[[thumbnails]] の name。省略時はすべて")] = None,
    bg_only: Annotated[
        bool,
        typer.Option(
            "--bg-only", help="背景だけを build/thumbnail/bg/<name>.png に書き出す（Aegisub の下敷き）"
        ),
    ] = False,
) -> None:
    """背景のフレームにサムネイル用の .ass を描いて、build/thumbnail/<name>.png に書き出す。"""
    require_tools()
    project = _load_project(project_dir)
    thumbnails = _select_named(
        project.config.thumbnails, name, table="[[thumbnails]]", example=THUMBNAIL_EXAMPLE
    )
    issues = _background_issues(project)
    analysis = analyze_thumbnails(project, thumbnails, bg_only=bg_only)
    issues += analysis.issues
    _print_issues(issues)
    if any(issue.level == "error" for issue in issues):
        raise typer.Exit(1)

    video = project.config.video
    for thumb in thumbnails:
        if bg_only:
            subtitles = fontsdir = None
            output = project.thumbnail_bg_output(thumb)
        else:
            # .ass は加工せずにそのまま描く（自動のフェードと曲名表示は入れない）
            subtitles = project.thumbnail_file(thumb).absolute()
            fontsdir = fonts.prepare_fontsdir(analysis.font_files[thumb.name], cache_dir() / "fontsets")
            output = project.thumbnail_output(thumb)
        spec = graph.StillSpec(
            size=project.thumbnail_size(thumb),
            background=project.background_path.absolute(),
            at=thumb.at,
            subtitles=subtitles,
            fontsdir=fontsdir,
            fit=video.fit,
            focus=project.thumbnail_focus(thumb),
            scale_flags=video.scale_flags,
            pad_color=video.pad_color,
        )
        try:
            run(graph.build_still_args(spec), output, total_s=0)
        except NoOutputError as e:
            raise NoOutputError(
                f"{e}。背景の終わり近くの at では、その時刻以降のフレームが無いことがあります"
            ) from e
        console.print(f"書き出しました: {output}（{output.stat().st_size:,} バイト）", markup=False)
        if windows_path := to_windows_path(output):
            console.print(f"  Windows: {windows_path}", markup=False)
