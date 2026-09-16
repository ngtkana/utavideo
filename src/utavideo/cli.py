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

from utavideo import description, fonts, graph, layout, subs
from utavideo.config import PROJECT_CONFIG_NAME, Thumbnail, cache_dir, load_user_config
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
    issues: list[subs.Issue] = []

    for label, path in [("audio.file", project.audio_path), ("lyrics.file", project.lyrics_path)]:
        if not path.is_file():
            issues.append(subs.Issue("error", f"{label} のファイルがありません: {path}"))
    if mode != "overlay":
        issues += _background_issues(project)

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
    font_issues, font_files = _check_fonts(script, search or _FontSearch.load())
    return Analysis(issues + font_issues, duration_s, lyrics, font_files)


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


def _check_fonts(script: pysubs2.SSAFile, search: _FontSearch) -> tuple[list[subs.Issue], tuple[Path, ...]]:
    """使っているフォントを探し、見つからないフォントのエラーと、はみ出しそうな行の警告を返す。"""
    resolution = fonts.resolve(search.index, subs.used_fonts(script))
    issues: list[subs.Issue] = []
    for name in resolution.missing:
        searched = ", ".join(map(str, search.dirs)) or "（なし）"
        issues.append(subs.Issue("error", f"フォント {name!r} が見つかりません（探した場所: {searched}）"))
    issues += layout.overflows(script, search.index.lookup)
    return issues, resolution.files


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
        focus=config.video.focus,
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
  3. utavideo check → utavideo build → utavideo release
  4. utavideo thumbnail --bg-only → Aegisub で src/thumbnail.ass を開いて文字を組む → utavideo thumbnail"""


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
        issues += [subs.Issue(i.level, f"サムネイル {thumb.name}: {i.message}") for i in found]
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


def _select_thumbnails(project: Project, name: str | None) -> tuple[Thumbnail, ...]:
    thumbnails = project.config.thumbnails
    if not thumbnails:
        _fail(f"utavideo.toml に [[thumbnails]] がありません。次を書き足してください:\n{THUMBNAIL_EXAMPLE}")
    if name is None:
        return thumbnails
    found = tuple(t for t in thumbnails if t.name == name)
    if not found:
        names = ", ".join(t.name for t in thumbnails)
        _fail(f"[[thumbnails]] に name = {name!r} がありません（あるのは {names}）")
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
    thumbnails = _select_thumbnails(project, name)
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
