"""書き出し前の検査。曲フォルダの状態を読み、Issue のリストを返す。"""

from dataclasses import dataclass
from pathlib import Path

import pysubs2

from utavideo import fonts, graph, layout, subs
from utavideo.config import cache_dir, load_user_config
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
