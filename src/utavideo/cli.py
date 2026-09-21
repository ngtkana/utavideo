"""utavideo コマンド。"""

import filecmp
import functools
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import pysubs2
import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeRemainingColumn

from utavideo import description, fonts, graph, layout, sample, subs
from utavideo.config import PROJECT_CONFIG_NAME, cache_dir, load_user_config
from utavideo.errors import UtavideoError
from utavideo.ffmpeg import (
    partial_path,
    probe_audio,
    replace_partial,
    require_tools,
    run,
    subtitles_filter_error,
)
from utavideo.names import has_date_prefix, slug_error, slug_from_dir_name
from utavideo.project import (
    VERSION_PATTERN,
    Project,
    ScaffoldResult,
    find_project_root,
    next_revision,
    require_usable_slug,
    scaffold,
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
    console.print(_NEXT_STEPS, markup=False)


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


@app.command("sample")
@_handle_errors
def sample_command(
    path: Annotated[Path, typer.Argument(help="作る見本の曲フォルダのパス（まだ無いパス）")],
    font: Annotated[
        str | None,
        typer.Option("--font", help="歌詞に使う実在のフォント名。省略時はフォントも合成する"),
    ] = None,
    small: Annotated[bool, typer.Option("--small", help="小さく速く作る（640x360・10fps）")] = False,
) -> None:
    """動作確認用の見本の曲フォルダを、合成した素材から作る。"""
    if path.exists():
        _fail(f"既にあります: {path}（作り直すときはフォルダごと消してください）")
    require_tools(subtitles=False)  # 素材を合成するだけで、歌詞は描かない
    try:
        result = sample.create(path, font=font, small=small)
    # path は「まだ無いパス」に自分で作ったもの。途中で失敗したら消して、同じパスでやり直せるようにする
    except BaseException:
        shutil.rmtree(path, ignore_errors=True)
        raise
    console.print(f"作成しました: {path}", markup=False)
    _print_scaffold(result, path)
    prefix = sample.command_prefix(font)
    console.print(f"次にやること:\n  cd {path}", markup=False)
    console.print(
        f"  {prefix}utavideo check → {prefix}utavideo build（他のコマンドは README.md）", markup=False
    )


@app.command()
@_handle_errors
def check(project_dir: ProjectOption = None) -> None:
    """設定・素材・歌詞・フォントを検査する。"""
    # 検査自体は ffprobe で音源を読むので要るが、libass は要らない。
    # 無いことは Issue にして、1回の check で直すべきことが全部並ぶようにする
    require_tools(subtitles=False)
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
    if (error := subtitles_filter_error()) is not None:
        issues.append(subs.Issue("error", error))
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
