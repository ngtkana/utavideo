"""utavideo コマンド。"""

import functools
import os
import re
import shutil
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from utavideo import (
    announce,
    build_all,
    description,
    fonts,
    graph,
    inputs,
    inst,
    layers,
    sample,
    shorts,
    status,
    subs,
    thumbnail,
    vertical,
)
from utavideo.analyze import (
    FontSearch,
    analyze,
    analyze_inst,
    analyze_shorts,
    analyze_thumbnails,
    analyze_vertical,
    background_issues,
    font_missing_message,
    layer_issues,
)
from utavideo.config import (
    PROJECT_CONFIG_NAME,
    Short,
    Thumbnail,
    Video,
    cache_dir,
    load_user_config,
)
from utavideo.console import console, err_console
from utavideo.errors import UtavideoError
from utavideo.ffmpeg import (
    LoudnormTarget,
    NoOutputError,
    measure_loudness,
    partial_path,
    replace_partial,
    require_tools,
    rubberband_filter_error,
    run,
    subtitles_filter_error,
    write_text,
)
from utavideo.names import has_date_prefix, slug_error, slug_from_dir_name
from utavideo.project import (
    SHORTS_EXAMPLE,
    THUMBNAIL_EXAMPLE,
    THUMBNAIL_TEMPLATE_PATH,
    VERSION_PATTERN,
    Project,
    ScaffoldResult,
    find_matching_release,
    find_project_root,
    next_revision,
    record_release_match,
    require_usable_slug,
    scaffold,
    to_windows_path,
)
from utavideo.render import Frame, VideoTarget, compose, compose_inst, frame_script, write_video

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="utavideo.toml と歌詞 .ass から歌動画を書き出す。",
)

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


def _render(project_dir: Path | None, mode: graph.Mode, label: str) -> Path:
    require_tools()
    project = _load_project(project_dir)
    # analyze が素材を読む前に取る（理由は inputs.snapshot）
    record = None
    if mode == "final":
        main_target = inputs.main_target(project)
        record = inputs.Record(main_target, inputs.snapshot(main_target))
    analysis = analyze(project, mode)
    _print_issues(analysis.issues)
    if not subs.ok(analysis.issues):
        raise typer.Exit(1)
    assert analysis.lyrics is not None and analysis.duration_s is not None and analysis.font_index is not None

    script = compose(project, analysis.lyrics, round(analysis.duration_s * 1000), mode, analysis.font_index)
    output = {
        "final": project.main_output,
        "preview": project.preview_bg_output,
        "overlay": project.overlay_output,
    }[mode]
    video = project.config.video
    # overlay は背景の無い透過動画（動画編集ソフトで自分の背景に重ねる用）なので、[[layers]] は重ねない
    layer_specs = (
        ()
        if mode == "overlay"
        else tuple(layers.spec(project.root, layer) for layer in project.config.layers)
    )
    target = VideoTarget(
        mode, video.size, video.focus, project.work_dir / f"{mode}.ass", output, label, layers=layer_specs
    )
    return write_video(project, script, target, analysis.duration_s, analysis.font_files, record)


def _print_scaffold(result: ScaffoldResult, root: Path) -> None:
    for path in result.created:
        console.print(f"  作成: {path.relative_to(root)}", markup=False)
    for path in result.skipped:
        console.print(f"  既にあるので変更なし: {path.relative_to(root)}", markup=False)


_NEXT_STEPS = """次にやること（詳しくは docs/workflow.md）:
  1. utavideo.toml の audio.file / video.background を合わせ、song を確認する
  2. utavideo preview-bg → Aegisub で src/lyrics.ass と build/preview/bg.mp4 を開いて歌詞を入れる
  3. utavideo check → utavideo build → utavideo release
  4. utavideo preview-bg --target thumbnail → Aegisub で src/thumbnail.ass を開いて文字を組む →
     utavideo thumbnail
  5. 縦型のショートを作るなら、utavideo.toml に [vertical] を書く →
     utavideo preview-bg（縦用 .ass を自動で作り、下敷きも書き出す）→ Aegisub で src/vertical.ass を
     組み、区間を置く → utavideo.toml に [[shorts]] → utavideo shorts"""


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


@app.command("fonts")
@_handle_errors
def fonts_command(
    name: Annotated[str | None, typer.Argument(help="調べるフォント名。省略時は使える名前を一覧する")] = None,
) -> None:
    """.ass に書けるフォント名（check が照合する名前）を探す。"""
    search = FontSearch.load()
    if name is not None:
        files = search.index.lookup(name)
        if not files:
            _fail(font_missing_message(name, search.dirs))
        for file in sorted(set(files)):
            console.print(str(file), markup=False)
        return
    if not search.dirs:
        console.print("探した場所: （なし）", markup=False)
        console.print(
            "環境変数 UTAVIDEO_FONT_DIRS か、ユーザー設定の font_dirs でフォントのある"
            "ディレクトリを指定してください",
            markup=False,
        )
        return
    console.print("探した場所: " + ", ".join(map(str, search.dirs)), markup=False)
    entries = sorted(
        {(match.display_name, file) for match in search.index.matches.values() for file in match.files}
    )
    for display_name, file in entries:
        console.print(f"{file} | {display_name}", markup=False)


@app.command()
@_handle_errors
def check(project_dir: ProjectOption = None) -> None:
    """設定・素材・歌詞・フォントを検査する。"""
    # 検査自体は ffprobe で音源を読むので要るが、libass は要らない。
    # 無いことは Issue にして、1回の check で直すべきことが全部並ぶようにする
    require_tools(subtitles=False)
    project = _load_project(project_dir)
    # フォントの一覧は、歌詞とサムネイルの検査で1回だけ読む
    search = FontSearch.load()
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
    if config.description is not None or config.announce is not None:
        user_config = load_user_config()
        if config.description is not None:
            issues += description.lint(project, user_config.description)
        if config.announce is not None:
            # 投稿するまでは毎回出てしまうので、uploads が無いことは announce でだけ警告する
            issues += announce.lint(
                config, user_config.announce, user_config.description, warn_no_uploads=False
            )
    for thumb in config.thumbnails:
        thumb_size = thumbnail.size(thumb, config.video.size)
        console.print(
            f"  サムネイル: {thumb.name}（{thumb_size[0]}x{thumb_size[1]}、{thumb.file}）", markup=False
        )
    # 背景のファイル自体の検査は analyze で済んでいる
    issues += analyze_thumbnails(project, config.thumbnails, bg_only=False, search=search).issues
    if analysis.lyrics is not None:
        issues += shorts.main_lyrics_issues(analysis.lyrics)
    # ショートを作らない曲では縦用 .ass を見ない（[vertical] だけ試しただけの曲で止めない）
    if config.shorts:
        size = config.vertical.size
        console.print(f"  縦用 .ass: {config.vertical.lyrics}（{size[0]}x{size[1]}）", markup=False)
        console.print(f"  ショート: {', '.join(s.name for s in config.shorts)}", markup=False)
        found = analyze_shorts(
            project, search, analysis.duration_s, analysis.lyrics, config.shorts, report_unused=True
        )
        issues += found.issues

    _print_issues(issues)
    if not subs.ok(issues):
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
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            help=(
                "書き出す対象。省略時は本編・縦型ショートの下敷き。thumbnail ですべての"
                "[[thumbnails]]、thumbnail:<name> で1つだけの下敷き（build/thumbnail/bg/<name>.png）"
            ),
        ),
    ] = None,
) -> None:
    """歌詞以外（背景・曲名表示・音声）を合成した、Aegisub 用のプレビュー動画を書き出す。

    utavideo.toml に [vertical] があれば、縦型のショートの下敷き（build/preview/vertical-bg.mp4）も
    作る。縦用 .ass（vertical.lyrics）がまだ無ければ、本編の歌詞から自動で作る。

    --target thumbnail（または thumbnail:<name>）で、サムネイルの下敷き
    （build/thumbnail/bg/<name>.png）を書き出す。
    """
    if target is not None:
        _render_thumbnail_bg(project_dir, target)
        return
    _render(project_dir, "preview", "preview-bg")
    project = _load_project(project_dir)
    if "vertical" in project.config.model_fields_set:
        _ensure_vertical_ass(project)
        _render_vertical_preview(project)


def _render_thumbnail_bg(project_dir: Path | None, target: str) -> None:
    """preview-bg --target thumbnail[:<name>] を処理する。"""
    if target != "thumbnail" and not target.startswith("thumbnail:"):
        _fail(f"--target には thumbnail か thumbnail:<name> を指定してください: {target}")
    name = target.removeprefix("thumbnail:") if target != "thumbnail" else None

    require_tools()
    project = _load_project(project_dir)
    thumbnails = _select_named(
        project.config.thumbnails, name, table="[[thumbnails]]", example=THUMBNAIL_EXAMPLE
    )
    issues = background_issues(project) + layer_issues(project)
    analysis = analyze_thumbnails(project, thumbnails, bg_only=True)
    issues += analysis.issues
    _print_issues(issues)
    if not subs.ok(issues):
        raise typer.Exit(1)

    video = project.config.video
    for thumb in thumbnails:
        output = _write_thumbnail(project, thumb, video, (), bg_only=True)
        console.print(f"書き出しました: {output}（{output.stat().st_size:,} バイト）", markup=False)
        if windows_path := to_windows_path(output):
            console.print(f"  Windows: {windows_path}", markup=False)


def _render_vertical_preview(project: Project) -> None:
    require_tools()
    search = FontSearch.load()
    inputs = analyze(project, "final", search)
    issues, duration_s = inputs.issues, inputs.duration_s
    checked = analyze_vertical(project, search)
    issues += checked.issues
    _print_issues(issues)
    if not subs.ok(issues):
        raise typer.Exit(1)
    assert checked.script is not None and duration_s is not None

    duration_ms = round(duration_s * 1000)
    overlay = vertical.overlay_text(project.config.overlay_text, project.config.vertical)
    script = compose(
        project, checked.script, duration_ms, "preview", search.index, no_vertical_fade=True, overlay=overlay
    )
    # 下敷きも完成図と同じ画面にする。本編の歌詞は真ん中の映像に入れ、縦用 .ass の行は入れない
    assert inputs.lyrics is not None
    frame_ass = frame_script(project, inputs.lyrics, duration_ms, search.index)
    layer_specs = tuple(layers.spec(project.root, layer) for layer in project.config.layers)
    frame = Frame(frame_ass, project.work_dir / "vertical-preview-frame.ass", layers=layer_specs)
    font_files = checked.font_files + inputs.font_files
    target = VideoTarget(
        "preview",
        project.config.vertical.size,
        vertical.focus(project.config.vertical, project.config.video.focus),
        project.work_dir / "vertical-preview.ass",
        vertical.preview_bg_output(project.build_dir),
        "preview-bg（縦）",
        frame=frame,
    )
    write_video(project, script, target, duration_s, font_files, None)


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
    write_text(project.title_output, title)
    write_text(project.description_output, body)
    console.print(title, markup=False)
    console.print()
    console.print(body, markup=False, end="")
    for path in (project.title_output, project.description_output):
        console.print(f"書き出しました: {path}", markup=False)


@app.command("announce")
@_handle_errors
def announce_command(project_dir: ProjectOption = None) -> None:
    """投稿した動画の URL と曲の情報から、SNS の告知文を build/announce.txt に書き出す。"""
    project = _load_project(project_dir)
    user_config = load_user_config()
    fmt = user_config.announce
    issues = announce.lint(project.config, fmt, user_config.description, warn_no_uploads=True)
    _print_issues(issues)
    # 誤った URL の告知文を投稿しないよう、description と違ってエラーがあれば書き出さない
    if not subs.ok(issues):
        _fail("告知文を書き出しませんでした")
    text = announce.render(project.config, fmt, user_config.description)
    write_text(project.announce_output, text)
    console.print(text, markup=False, end="")
    console.print(f"長さ: {announce.weight(text)} / {fmt.max_weight}（X の数え方）", markup=False)
    console.print(f"書き出しました: {project.announce_output}", markup=False)


@app.command()
@_handle_errors
def release(
    project_dir: ProjectOption = None,
    short: Annotated[
        str | None,
        typer.Option("--short", help="[[shorts]] の name。指定すると本編でなくこのショートを release する"),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version", help="音源のバージョン。例: v1.0。省略時は audio.file のファイル名から"),
    ] = None,
    allow_stale: Annotated[bool, typer.Option(help="書き出した後に入力が変わっていてもコピーする")] = False,
) -> None:
    """build/main.mp4 を release/<slug>-<音源のバージョン>.<何本目か>.mp4 にコピーする。

    --short <name> を付けると、本編の代わりにそのショート（wide があれば両方）を release する。
    """
    project = _load_project(project_dir)
    if short is None:
        _release_one(
            project,
            project.main_output,
            "utavideo build",
            version,
            allow_stale,
            suffix="",
            stale_target=inputs.main_target(project),
        )
        return

    (selected,) = _select_named(project.config.shorts, short, table="[[shorts]]", example=SHORTS_EXAMPLE)
    stale_target = inputs.shorts_target(project, selected)
    rebuild_command = f"utavideo shorts --name {selected.name}"
    _release_one(
        project,
        shorts.output_path(project.build_dir, selected),
        rebuild_command,
        version,
        allow_stale,
        suffix=f"-shorts-{selected.name}",
        stale_target=stale_target,
    )
    if selected.wide:
        _release_one(
            project,
            shorts.output_path(project.build_dir, selected, wide=True),
            rebuild_command,
            version,
            allow_stale,
            suffix=f"-shorts-{selected.name}-wide",
            stale_target=stale_target,
        )


def _release_one(
    project: Project,
    source: Path,
    rebuild_command: str,
    version: str | None,
    allow_stale: bool,
    *,
    suffix: str,
    stale_target: inputs.RecordTarget,
) -> None:
    """release の1本分（本編・ショート・ショートの wide のいずれか）。"""
    label = source.relative_to(project.root).as_posix()
    if not source.is_file():
        _fail(f"{label} がありません。先に {rebuild_command} を実行してください")

    resolved = version or project.version
    if resolved is None:
        _fail("audio.file のファイル名に vX.Y が無いので --version で指定してください")
    if not re.fullmatch(VERSION_PATTERN, resolved, re.IGNORECASE):
        _fail(f"音源のバージョンは v1.0 のような vX.Y の形で指定してください: {resolved}")
    resolved = resolved.lower()

    if not allow_stale and (stale := inputs.stale_inputs(stale_target)):
        _fail(f"{stale}。{rebuild_command} で書き出し直すか --allow-stale を付けてください")

    # 書き出し直しただけの動画を別の番号で公開しないよう、公開済みのものと中身を比べる
    same, dest, _ = find_matching_release(project, resolved, source, suffix=suffix)
    if same is not None:
        record_release_match(project, resolved, source, same, suffix=suffix)
        _fail(f"同じ内容が既にあります: {same}（コピーしません）")

    if dest.exists():
        _fail(f"既にあります: {dest}（上書きはしません）")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = partial_path(dest)
    shutil.copy2(source, tmp)
    replace_partial(tmp, dest)
    record_release_match(project, resolved, source, dest, suffix=suffix)
    console.print(f"コピーしました: {dest}", markup=False)


@app.command("status")
@_handle_errors
def status_command(project_dir: ProjectOption = None) -> None:
    """build・概要欄・告知文・release の状態を一覧する（git status 風）。"""
    project = _load_project(project_dir)
    console.print(status.render(status.collect(project)), markup=False)


@app.command("shorts")
@_handle_errors
def shorts_command(
    project_dir: ProjectOption = None,
    name: Annotated[str | None, typer.Option("--name", help="[[shorts]] の name。省略時はすべて")] = None,
) -> None:
    """縦型の切り抜きショートを build/shorts/<name>.mp4 に書き出す。"""
    require_tools()
    project = _load_project(project_dir)
    config = project.config
    selected = _select_named(config.shorts, name, table="[[shorts]]", example=SHORTS_EXAMPLE)
    search = FontSearch.load()
    any_wide = any(s.wide for s in selected)
    # blur は真ん中に本編の映像を置くので、常に本編の .ass を描く
    records: dict[str, inputs.Record] = {}
    for short in selected:
        target = inputs.shorts_target(project, short)
        records[short.name] = inputs.Record(target, inputs.snapshot(target))
    vertical_analysis = analyze(project, "final", search)
    issues, duration_s, lyrics = (
        vertical_analysis.issues,
        vertical_analysis.duration_s,
        vertical_analysis.lyrics,
    )
    analysis = analyze_shorts(project, search, duration_s, lyrics, selected, report_unused=name is None)
    issues += analysis.issues
    _print_issues(issues)
    if not subs.ok(issues):
        raise typer.Exit(1)
    assert analysis.script is not None and duration_s is not None and lyrics is not None

    fps = config.video.fps
    duration_ms = round(duration_s * 1000)
    # 本編の .ass はどのショートでも同じなので、合成は1回だけ
    wide_script = compose(project, lyrics, duration_ms, "final", search.index) if any_wide else None
    frame_ass = frame_script(project, lyrics, duration_ms, search.index)
    # blur では本編の .ass も描くので、そのフォントも渡す（どのショートでも同じ）
    font_files = analysis.font_files + vertical_analysis.font_files
    default_focus = vertical.focus(config.vertical, config.video.focus)
    overlay = vertical.overlay_text(config.overlay_text, config.vertical)
    # [[layers]] はどのショートでも同じ。区間との重なりは本編と同じ enable の仕組みに任せる
    layer_specs = tuple(layers.spec(project.root, layer) for layer in config.layers)
    for short in selected:
        section = analysis.sections[short.name]
        clip = graph.Clip(*shorts.clip_frames(section, fps), config.vertical.audio_fade_ms)
        length_s = clip.duration_s(fps)
        # .ass の時刻はずらさない。区間の頭をまたぐ行の \\move・\\fad を本編と同じ状態で描くため
        in_section = shorts.lines_in_sections(analysis.script, [section])
        script = compose(
            project, in_section, duration_ms, "final", search.index, no_vertical_fade=True, overlay=overlay
        )
        frame = Frame(frame_ass, shorts.work_ass_path(project.work_dir, short, "frame"), layers=layer_specs)
        target = VideoTarget(
            "final",
            config.vertical.size,
            shorts.resolve_focus(short, default_focus),
            shorts.work_ass_path(project.work_dir, short),
            shorts.output_path(project.build_dir, short),
            f"shorts {short.name}",
            clip,
            frame,
        )
        write_video(project, script, target, length_s, font_files, records[short.name])
        if not short.wide:
            continue
        assert wide_script is not None
        wide_target = VideoTarget(
            "final",
            config.video.size,
            config.video.focus,
            shorts.work_ass_path(project.work_dir, short, "wide"),
            shorts.output_path(project.build_dir, short, wide=True),
            f"shorts {short.name}（wide）",
            clip,
            layers=layer_specs,
        )
        # 本編と同じ .ass・同じ大きさで描くので、区間のコマは build/main.mp4 と一致する
        # （wide は shorts:<name> の記録で代表させ、個別の記録は持たない）
        write_video(project, wide_script, wide_target, length_s, vertical_analysis.font_files, None)


@app.command("inst")
@_handle_errors
def inst_command(
    project_dir: ProjectOption = None,
    keys: Annotated[
        str, typer.Option("--keys", help="半音単位のキー。カンマ区切りで複数指定できる（例: -1,-2,-3）")
    ] = "0",
    include_lyrics: Annotated[
        bool,
        typer.Option("--lyrics", help="本編と同じ歌詞も焼き込む（既定では曲名・アーティスト・キーだけ）"),
    ] = False,
) -> None:
    """歌唱練習用に、キーを変えた伴奏の動画を build/inst/<slug>-key<N>.mp4 に書き出す。

    既定では歌詞を描かない（--lyrics で本編と同じ歌詞も焼き込む）。
    """
    require_tools()
    project = _load_project(project_dir)
    parsed_keys = inst.parse_keys(keys)
    search = FontSearch.load()
    # analyze が素材を読む前に、キーごとの記録の元になる snapshot を取る
    records = {}
    for key in parsed_keys:
        record_target = inputs.inst_target(project, key)
        records[key] = inputs.Record(record_target, inputs.snapshot(record_target))
    analysis = analyze_inst(project, parsed_keys, include_lyrics=include_lyrics, search=search)
    _print_issues(analysis.issues)
    if not subs.ok(analysis.issues):
        raise typer.Exit(1)
    assert analysis.lyrics is not None and analysis.duration_s is not None and analysis.font_index is not None

    method: graph.PitchMethod = "rubberband" if rubberband_filter_error() is None else "atempo"
    if method == "atempo":
        console.print(
            "rubberband フィルタが使えないので、asetrate+atempo でキーを変えます（音質は劣ります）",
            markup=False,
        )
    loudnorm_target = LoudnormTarget()
    measured = measure_loudness(project.inst_audio_path.absolute(), loudnorm_target)

    duration_ms = round(analysis.duration_s * 1000)
    video = project.config.video
    for key in parsed_keys:
        label = inst.key_label(key)
        script = compose_inst(
            project, analysis.lyrics, duration_ms, analysis.font_index, label, include_lyrics=include_lyrics
        )
        target = VideoTarget(
            "final",
            video.size,
            video.focus,
            inst.work_ass_path(project.work_dir, key),
            inst.output_path(project.build_dir, project.slug, key),
            f"inst {label}",
            pitch=graph.Pitch(inst.pitch_ratio(key), method),
            loudnorm=graph.Loudnorm(loudnorm_target, measured),
            audio=project.inst_audio_path,
        )
        write_video(project, script, target, analysis.duration_s, analysis.font_files, records[key])


def _ensure_vertical_ass(project: Project) -> None:
    """本編の歌詞 .ass から、縦型のショート用の .ass（vertical.lyrics）を作る。既にあれば何もしない。

    作り直すときは、消してから preview-bg を実行する（vertical.lyrics を上書きしない）。
    """
    config = project.config
    dest = vertical.lyrics_path(project.root, config.vertical)
    if dest.exists():
        return
    # preview-bg が先に本編の歌詞（lyrics.file）の存在を検査しているので、ここでは検査しない
    source = project.lyrics_path
    size = config.vertical.size
    script = vertical.convert(
        subs.load(source),
        size=size,
        video_file=_path_from(dest.parent, vertical.preview_bg_output(project.build_dir)),
        source_dir=_path_from(dest.parent, source.parent),
        band_video_size=config.video.size,
    )
    write_text(dest, script.to_string("ass"))

    console.print(f"作成しました: {dest}（{size[0]}x{size[1]}）", markup=False)
    # 歌詞は本編の映像に入るので写していない。直すのは区間の指定と帯の文字だけ。曲名表示は自動で帯に入る
    next_step = (
        "Aegisub で開き、区間をスタイル Short のコメント行で置く"
        f"（曲名表示は自動で帯に入る。帯に文字を足すならスタイル {vertical.BAND_STYLE} で書く）"
    )
    console.print(f"次にやること（詳しくは docs/workflow.md）: {next_step}", markup=False)


def _path_from(start: Path, path: Path) -> str:
    """start から見た path。Aegisub の Video File: に書くので / で区切る。"""
    try:
        return Path(os.path.relpath(path, start)).as_posix()
    except ValueError:  # Windows でドライブが違うと相対パスにできない
        return path.absolute().as_posix()


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


@app.command("thumbnail")
@_handle_errors
def thumbnail_command(
    project_dir: ProjectOption = None,
    name: Annotated[str | None, typer.Option("--name", help="[[thumbnails]] の name。省略時はすべて")] = None,
) -> None:
    """背景のフレームにサムネイル用の .ass を描いて、build/thumbnail/<name>.png に書き出す。"""
    require_tools()
    project = _load_project(project_dir)
    thumbnails = _select_named(
        project.config.thumbnails, name, table="[[thumbnails]]", example=THUMBNAIL_EXAMPLE
    )
    issues = background_issues(project) + layer_issues(project)
    analysis = analyze_thumbnails(project, thumbnails, bg_only=False)
    issues += analysis.issues
    _print_issues(issues)
    if not subs.ok(issues):
        raise typer.Exit(1)

    video = project.config.video
    for thumb in thumbnails:
        font_files = analysis.font_files.get(thumb.name, ())
        target = inputs.thumbnail_target(project, thumb)
        record = inputs.Record(target, inputs.snapshot(target))
        output = _write_thumbnail(project, thumb, video, font_files, bg_only=False, record=record)
        console.print(f"書き出しました: {output}（{output.stat().st_size:,} バイト）", markup=False)
        if windows_path := to_windows_path(output):
            console.print(f"  Windows: {windows_path}", markup=False)


def _write_thumbnail(
    project: Project,
    thumb: Thumbnail,
    video: Video,
    font_files: tuple[Path, ...],
    *,
    bg_only: bool,
    record: inputs.Record | None = None,
) -> Path:
    """背景のフレームに1本のサムネイルを書き出し、出力先を返す。

    thumbnail_command・preview-bg・build-all から呼ぶ（画面への表示はそれぞれの呼び出し側が行う）。
    record は bg_only のとき渡さない（bg は status の対象ではないので記録しない）。
    """
    if bg_only:
        subtitles = fontsdir = None
        output = thumbnail.bg_output_path(project.build_dir, thumb)
    else:
        # .ass は加工せずにそのまま描く（自動のフェードと曲名表示は入れない）
        subtitles = thumbnail.file_path(project.root, thumb).absolute()
        fontsdir = fonts.prepare_fontsdir(font_files, cache_dir() / "fontsets")
        output = thumbnail.output_path(project.build_dir, thumb)
    at = thumb.at or 0.0
    active_layers = tuple(
        layers.spec(project.root, layer, timed=False)
        for layer in project.config.layers
        if layers.active_at(layer, at)
    )
    spec = graph.StillSpec(
        size=thumbnail.size(thumb, video.size),
        background=project.background_path.absolute(),
        at=thumb.at,
        subtitles=subtitles,
        fontsdir=fontsdir,
        fit=video.fit,
        focus=thumbnail.focus(thumb, video.focus),
        scale_flags=video.scale_flags,
        pad_color=video.pad_color,
        layers=active_layers,
    )
    inputs.unlink_stale_record(record)
    try:
        run(graph.build_still_args(spec), output, total_s=0)
    except NoOutputError as e:
        raise NoOutputError(
            f"{e}。背景の終わり近くの at では、その時刻以降のフレームが無いことがあります"
        ) from e
    inputs.save_record(record)
    return output


@app.command("build-all")
@_handle_errors
def build_all_command(project_dir: ProjectOption = None) -> None:
    """曲フォルダで今作れるものをまとめて作る（build・description・announce・thumbnail）。"""
    require_tools()
    project = _load_project(project_dir)
    search = FontSearch.load()
    plan = build_all.collect(project, search)
    for target in plan.targets:
        if target.state == "run":
            _run_build_all_target(project, search, target.name)
    console.print(build_all.render(plan), markup=False)


def _run_build_all_target(project: Project, search: FontSearch, name: str) -> None:
    """build-all の「実行」対象を1つ実際に書き出す。

    build_all.collect はエラーの有無しか見ていないので、それぞれのコマンドと同じく警告も表示する。
    collect から実行までの間に状態が変わっていないかも、書き出す前にもう一度確かめる
    （announce・thumbnail はエラーがあれば typer.Exit で止める。description は元のコマンドと同じく
    警告があっても書き出す）。
    """
    if name == "build":
        _render(project.root, "final", "build")
    elif name == "description":
        fmt = load_user_config().description
        if project.config.description is not None:
            _print_issues(description.lint(project, fmt))
        write_text(project.title_output, description.render_title(project.config, fmt))
        write_text(project.description_output, description.render_body(project.config, fmt))
    elif name == "announce":
        user_config = load_user_config()
        issues = announce.lint(
            project.config, user_config.announce, user_config.description, warn_no_uploads=True
        )
        _print_issues(issues)
        if not subs.ok(issues):
            raise typer.Exit(1)
        text = announce.render(project.config, user_config.announce, user_config.description)
        write_text(project.announce_output, text)
    else:
        thumb_name = name.removeprefix("thumbnail:")
        thumb = next(t for t in project.config.thumbnails if t.name == thumb_name)
        issues = background_issues(project) + layer_issues(project)
        analysis = analyze_thumbnails(project, (thumb,), bg_only=False, search=search)
        issues += analysis.issues
        _print_issues(issues)
        if not subs.ok(issues):
            raise typer.Exit(1)
        font_files = analysis.font_files.get(thumb_name, ())
        thumb_target = inputs.thumbnail_target(project, thumb)
        record = inputs.Record(thumb_target, inputs.snapshot(thumb_target))
        _write_thumbnail(project, thumb, project.config.video, font_files, bg_only=False, record=record)
