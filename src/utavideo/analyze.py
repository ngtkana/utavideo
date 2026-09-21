"""書き出し前の検査。曲フォルダの状態を読み、Issue のリストを返す。"""

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import pysubs2

from utavideo import fonts, graph, layout, shorts, subs
from utavideo.config import Layout, Short, Thumbnail, cache_dir, load_user_config
from utavideo.console import err_console
from utavideo.ffmpeg import FFmpegError, probe_audio, probe_duration
from utavideo.project import Project
from utavideo.render import compose
from utavideo.timecode import format_time


@dataclass(frozen=True)
class Analysis:
    issues: list[subs.Issue]
    duration_s: float | None
    lyrics: pysubs2.SSAFile | None
    font_files: tuple[Path, ...]
    font_index: fonts.FontIndex | None = None

    @property
    def ok(self) -> bool:
        return all(issue.level != "error" for issue in self.issues)


def analyze(project: Project, mode: graph.Mode, search: "FontSearch | None" = None) -> Analysis:
    """書き出しに必要なものが揃っているかを調べる。preview では歌詞の行の中身は問わない。"""
    config = project.config
    issues, duration_s = audio_issues(project)
    if not project.lyrics_path.is_file():
        issues.append(subs.Issue("error", f"lyrics.file のファイルがありません: {project.lyrics_path}"))
    if mode != "overlay":
        issues += background_issues(project)

    lyrics = subs.load(project.lyrics_path) if project.lyrics_path.is_file() else None
    if lyrics is None or duration_s is None:
        return Analysis(issues, duration_s, lyrics, ())

    duration_ms = round(duration_s * 1000)
    target = lyrics if mode != "preview" else subs.without_events(lyrics)
    issues += subs.lint(target, size=config.video.size, duration_ms=duration_ms, overlay=config.overlay_text)

    search = search or FontSearch.load()
    script = compose(project, lyrics, duration_ms, mode, search.index)
    font_issues, font_files = check_fonts(script, search)
    return Analysis(issues + font_issues, duration_s, lyrics, font_files, search.index)


def audio_issues(project: Project) -> tuple[list[subs.Issue], float | None]:
    """音源のファイルと音声の検査と、音源の長さ（秒。読めなければ None）。"""
    path = project.audio_path
    if not path.is_file():
        return [subs.Issue("error", f"audio.file のファイルがありません: {path}")], None
    audio = probe_audio(path)
    if not audio.has_sound:
        return [subs.Issue("error", f"audio.file に音声が入っていません: {path}")], audio.duration_s
    return [], audio.duration_s


def background_issues(project: Project) -> list[subs.Issue]:
    path = project.background_path
    if not path.is_file():
        return [subs.Issue("error", f"video.background のファイルがありません: {path}")]
    ext = path.suffix.lower()
    if ext not in graph.IMAGE_EXTS | graph.ANIMATED_EXTS:
        return [subs.Issue("error", f"video.background の形式に対応していません: {ext}")]
    return []


@dataclass(frozen=True)
class FontSearch:
    dirs: list[Path]
    index: fonts.FontIndex

    @classmethod
    def load(cls) -> "FontSearch":
        dirs = load_user_config().font_dirs
        cache_file = cache_dir() / "fonts.json"
        if not cache_file.exists():
            # 進捗であって出力ではないので、fonts <名前> をスクリプトから使えるよう stderr に出す
            err_console.print("フォント一覧を作成しています（初回のみ時間がかかります）…")
        return cls(dirs, fonts.load_index(dirs, cache_file))


def check_fonts(
    script: pysubs2.SSAFile, search: FontSearch, *, overflows: bool = True
) -> tuple[list[subs.Issue], tuple[Path, ...]]:
    """使っているフォントを探し、見つからないフォントのエラーと、はみ出しそうな行の警告を返す。"""
    resolution = fonts.resolve(search.index, subs.used_fonts(script))
    issues: list[subs.Issue] = []
    for name in resolution.missing:
        issues.append(subs.Issue("error", font_missing_message(name, search.dirs)))
    if overflows:
        issues += layout.overflows(script, search.index.lookup)
    return issues, resolution.files


def font_missing_message(name: str, font_dirs: list[Path]) -> str:
    """見つからない理由として多いもの（ファイル名を書いた・探す場所が無い）を添える。"""
    searched = ", ".join(map(str, font_dirs)) or "（なし）"
    path = Path(name)
    if path.suffix.lower() in fonts.FONT_EXTS:
        hint = f"。ファイル名ではなくフォント名を指定してください（例: {path.stem}）"
    elif not font_dirs:
        hint = (
            "。環境変数 UTAVIDEO_FONT_DIRS か、"
            "ユーザー設定の font_dirs でフォントのあるディレクトリを指定してください"
        )
    else:
        hint = ""
    return f"フォント {name!r} が見つかりません（探した場所: {searched}）{hint}"


def vertical_inputs(project: Project, search: FontSearch, *, draws_main: bool) -> Analysis:
    """縦の書き出しに要るものの検査と、音源の長さ・本編の .ass（無ければ None）。

    draws_main は本編の映像も描くとき（blur の真ん中、wide の版）で、本編の .ass とフォントも
    build と同じ条件で検査する。描かないなら、本編の .ass は突き合わせと LayoutRes にだけ使い、
    フォントは縦用 .ass のものだけでよい（文字が潰れる LayoutRes は本編の書き出しと同じく止める）。
    """
    if draws_main:
        return analyze(project, "final", search)
    issues, duration_s = audio_issues(project)
    issues += background_issues(project)
    lyrics = subs.load(project.lyrics_path) if project.lyrics_path.is_file() else None
    if lyrics is not None:
        issues += subs.layout_res_issues(lyrics)
    return Analysis(issues, duration_s, lyrics, ())


@dataclass(frozen=True)
class VerticalAnalysis:
    issues: list[subs.Issue]
    script: pysubs2.SSAFile | None  # 読めなかったときは None
    font_files: tuple[Path, ...]


def analyze_vertical(
    project: Project, search: FontSearch, *, layouts: Collection[Layout]
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
    composed = compose(project, script, 0, "final", search.index, no_vertical_fade=True, overlay=overlay)
    font_issues, font_files = check_fonts(composed, search, overflows=False)
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
    search: FontSearch,
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
    search: FontSearch,
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
