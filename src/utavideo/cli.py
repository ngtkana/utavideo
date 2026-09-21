"""utavideo コマンド。"""

import filecmp
import functools
import os
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from utavideo import announce, description, fonts, graph, inputs, sample, shorts, subs, vertical
from utavideo.analyze import (
    FontSearch,
    analyze,
    analyze_shorts,
    analyze_vertical,
    background_issues,
    check_fonts,
    font_missing_message,
    vertical_inputs,
)
from utavideo.config import (
    PROJECT_CONFIG_NAME,
    Layout,
    Short,
    Thumbnail,
    cache_dir,
    load_user_config,
)
from utavideo.console import console, err_console
from utavideo.errors import UtavideoError
from utavideo.ffmpeg import (
    FFmpegError,
    NoOutputError,
    partial_path,
    probe_duration,
    replace_partial,
    require_tools,
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
    find_project_root,
    next_revision,
    require_usable_slug,
    scaffold,
    to_windows_path,
)
from utavideo.render import Frame, VideoTarget, compose, frame_script, write_video
from utavideo.timecode import format_time

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
    built_inputs = inputs.snapshot(project) if mode == "final" else None
    analysis = analyze(project, mode)
    _print_issues(analysis.issues)
    if not analysis.ok:
        raise typer.Exit(1)
    assert analysis.lyrics is not None and analysis.duration_s is not None and analysis.font_index is not None

    script = compose(project, analysis.lyrics, round(analysis.duration_s * 1000), mode, analysis.font_index)
    output = {
        "final": project.main_output,
        "preview": project.preview_bg_output,
        "overlay": project.overlay_output,
    }[mode]
    video = project.config.video
    target = VideoTarget(mode, video.size, video.focus, project.work_dir / f"{mode}.ass", output, label)
    return write_video(project, script, target, analysis.duration_s, analysis.font_files, built_inputs)


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


def _render_vertical_preview(project_dir: Path | None) -> None:
    require_tools()
    project = _load_project(project_dir)
    layouts = project.vertical_layouts
    # 下敷きは、実際に使う画面に合わせる。blur が1本でもあれば、真ん中に本編の映像を置く
    layout_: Layout = "blur" if "blur" in layouts else "reframe"
    search = FontSearch.load()
    inputs = vertical_inputs(project, search, draws_main=layout_ == "blur")
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
    script = compose(
        project, checked.script, duration_ms, "preview", search.index, no_vertical_fade=True, overlay=overlay
    )
    frame, font_files = None, checked.font_files
    if layout_ == "blur":
        # 下敷きも完成図と同じ画面にする。本編の歌詞は真ん中の映像に入れ、縦用 .ass の行は入れない
        assert inputs.lyrics is not None
        frame_ass = frame_script(project, inputs.lyrics, duration_ms, search.index)
        frame = Frame(frame_ass, project.work_dir / "vertical-preview-frame.ass")
        font_files += inputs.font_files
    target = VideoTarget(
        "preview",
        project.config.vertical.size,
        project.vertical_focus,
        project.work_dir / "vertical-preview.ass",
        project.vertical_preview_bg_output,
        "preview-bg --vertical",
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
    if any(issue.level == "error" for issue in issues):
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
    version: Annotated[
        str | None,
        typer.Option("--version", help="音源のバージョン。例: v1.0。省略時は audio.file のファイル名から"),
    ] = None,
    allow_stale: Annotated[
        bool, typer.Option(help="build/main.mp4 を書き出した後に入力が変わっていてもコピーする")
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

    if not allow_stale and (stale := inputs.stale_inputs(project)):
        _fail(f"{stale}。build し直すか --allow-stale を付けてください")

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
    search = FontSearch.load()
    layouts: list[Layout] = [project.short_layout(short) for short in selected]
    any_blur, any_wide = "blur" in layouts, any(s.wide for s in selected)
    # wide は本編と同じ画面、blur は真ん中に本編の映像を置くので、どちらも本編の .ass を描く
    draws_main = any_blur or any_wide
    inputs = vertical_inputs(project, search, draws_main=draws_main)
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
    wide_script = frame_ass = None
    if draws_main:
        assert lyrics is not None
        if any_wide:
            wide_script = compose(project, lyrics, duration_ms, "final", search.index)
        if any_blur:
            frame_ass = frame_script(project, lyrics, duration_ms, search.index)
    # blur では本編の .ass も描くので、そのフォントも渡す（どのショートでも同じ）
    blur_font_files = analysis.font_files + inputs.font_files
    for short, layout_ in zip(selected, layouts, strict=True):
        section = analysis.sections[short.name]
        blur = layout_ == "blur"
        clip = graph.Clip(*shorts.clip_frames(section, fps), config.vertical.audio_fade_ms)
        length_s = clip.duration_s(fps)
        # .ass の時刻はずらさない。区間の頭をまたぐ行の \\move・\\fad を本編と同じ状態で描くため
        in_section = shorts.lines_in_sections(analysis.script, [section], vertical_only=blur)
        overlay = project.vertical_script_overlay_text([layout_])
        script = compose(
            project, in_section, duration_ms, "final", search.index, no_vertical_fade=True, overlay=overlay
        )
        frame, font_files = None, analysis.font_files
        if blur:
            assert frame_ass is not None
            frame = Frame(frame_ass, project.short_work_ass(short, "frame"))
            font_files = blur_font_files
        target = VideoTarget(
            "final",
            config.vertical.size,
            project.short_focus(short),
            project.short_work_ass(short),
            project.short_output(short),
            f"shorts {short.name}",
            clip,
            frame,
        )
        write_video(project, script, target, length_s, font_files, None)
        if not short.wide:
            continue
        assert wide_script is not None
        wide_target = VideoTarget(
            "final",
            config.video.size,
            config.video.focus,
            project.short_work_ass(short, "wide"),
            project.short_output(short, wide=True),
            f"shorts {short.name}（wide）",
            clip,
        )
        # 本編と同じ .ass・同じ大きさで描くので、区間のコマは build/main.mp4 と一致する
        write_video(project, wide_script, wide_target, length_s, inputs.font_files, None)


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
    write_text(dest, conversion.script.to_string("ass"))

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
    project: Project, thumbnails: tuple[Thumbnail, ...], *, bg_only: bool, search: FontSearch | None = None
) -> ThumbnailAnalysis:
    """サムネイルごとに書き出せるかを調べる。背景のファイル自体の検査（background_issues）は呼び出し側で行う。

    bg_only では at だけを見る（.ass はまだ無くてよい）。
    """
    issues: list[subs.Issue] = []
    font_files: dict[str, tuple[Path, ...]] = {}
    background = project.background_path
    usable = not background_issues(project)
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
        search = FontSearch.load()

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
    project: Project, thumb: Thumbnail, search: FontSearch, font_files: dict[str, tuple[Path, ...]]
) -> list[subs.Issue]:
    path = project.thumbnail_file(thumb)
    if not path.is_file():
        return [subs.Issue("error", f"file のファイルがありません: {path}")]
    try:
        script = subs.load(path)
    except subs.SubtitleError as e:
        return [subs.Issue("error", str(e))]
    issues = subs.lint_still(script, size=project.thumbnail_size(thumb))
    font_issues, font_files[thumb.name] = check_fonts(script, search)
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
    issues = background_issues(project)
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
