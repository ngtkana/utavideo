"""書き出し前の検査。曲フォルダの状態を読み、Issue のリストを返す。"""

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import pysubs2

from utavideo import fonts, graph, layout, subs
from utavideo.config import Layout, cache_dir, load_user_config
from utavideo.console import err_console
from utavideo.ffmpeg import probe_audio
from utavideo.project import Project
from utavideo.render import compose


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
