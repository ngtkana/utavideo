"""MuseScore の楽譜 (.mscz) を横1段のPNGに描く。

.mscz → MusicXML（MuseScore CLI）→ 横1段のSVG（Verovio）→ PNG（resvg-py）の順に変換する。
音源との同期・ffmpegへの統合・inst コマンドへの組み込みはここでは扱わない。
"""

import os
import re
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path

import resvg_py
import verovio

from utavideo.errors import UtavideoError


class ScoreError(UtavideoError):
    """MuseScore CLI が見つからない、または楽譜を描けなかった。"""


_MUSESCORE_ENV = "UTAVIDEO_MUSESCORE"
_MUSESCORE_NAMES = ("mscore", "musescore4", "MuseScore4", "mscore4portable")
# Homebrew等でPATHに入らないことが多いmacOSのアプリバンドル内バイナリ
_MACOS_APP_PATH = Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore")


def find_musescore() -> str | None:
    """MuseScore 4 の実行ファイルを探す。見つからなければ None。"""
    if env := os.environ.get(_MUSESCORE_ENV):
        return env
    for name in _MUSESCORE_NAMES:
        if path := shutil.which(name):
            return path
    if _MACOS_APP_PATH.exists():
        return str(_MACOS_APP_PATH)
    return None


def require_musescore() -> str:
    """使えなければ、利用者への案内つきで止める。"""
    musescore = find_musescore()
    if musescore is None:
        raise ScoreError(
            "MuseScore 4 の実行ファイルが見つかりません。MuseScore 4 をインストールするか、"
            f"環境変数 {_MUSESCORE_ENV} に実行ファイルのパスを指定してください"
        )
    return musescore


def to_musicxml(mscz_path: Path, musescore: str) -> str:
    """.mscz を MusicXML に変換して読む（元のファイルは書き換えない）。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "score.musicxml"
        try:
            result = subprocess.run(
                [musescore, "-o", str(out_path), str(mscz_path)],
                capture_output=True,
                text=True,
                errors="replace",
            )
        except OSError as e:
            raise ScoreError(f"{musescore} を実行できません: {e}") from e
        if result.returncode != 0 or not out_path.exists():
            tail = (result.stderr.strip() or result.stdout.strip())[-500:]
            raise ScoreError(f"MuseScore での MusicXML への変換に失敗しました: {tail}")
        return out_path.read_text(encoding="utf-8")


_RENDER_OPTIONS = {
    "breaks": "none",
    "adjustPageHeight": True,
    "pageWidth": 100000,  # Verovioが受け付ける最大値。breaks:noneでは実際の幅はこれを超えて伸びる
    "pageMarginLeft": 20,
    "pageMarginRight": 20,
    "footer": "none",
    "header": "none",
}

# Verovioは、コード記号中の♯♭やテンポのメトロノーム記号のようにMEIの一般テキストに埋め込まれた
# SMuFL文字(私用領域 U+E000-U+F8FF)を<path>化せず、テキストとして書き出す。font-family="Leipzig"
# のように実在しないフォント名が付くことも、font-family属性自体が無いこともあり、どちらにせよ
# ラスタライザは別の（無関係な字形を持つ）フォントにフォールバックしてしまう。コードポイントで
# 検出し、同梱のBravura Textを強制する(検証: issue #140)
_BUNDLED_FONT_FAMILY = "Bravura Text"
_BUNDLED_FONT_TEMPLATE = ("score-fonts", "BravuraText.otf")
_SMUFL_PRIVATE_USE_AREA = re.compile(r"[-]")
_TSPAN_WITH_TEXT = re.compile(r'(<tspan\b)((?:[^>"]|"[^"]*")*)(>)([^<]*)(</tspan>)')


def _substitute_missing_font(svg: str) -> str:
    """SMuFL文字を含むテキストのフォントを、同梱のBravura Textに強制する。"""

    def replace(m: re.Match[str]) -> str:
        open_tag, attrs, close_bracket, text, close_tag = m.groups()
        if not _SMUFL_PRIVATE_USE_AREA.search(text):
            return m.group(0)
        attrs = re.sub(r'\s*font-family="[^"]*"', "", attrs)
        return f'{open_tag}{attrs} font-family="{_BUNDLED_FONT_FAMILY}"{close_bracket}{text}{close_tag}'

    return _TSPAN_WITH_TEXT.sub(replace, svg)


def render_horizontal_svg(musicxml: str, *, scale: int = 40) -> str:
    """MusicXML を横1段の連続レイアウトのSVGに描く。"""
    tk = verovio.toolkit()
    tk.setOptions({**_RENDER_OPTIONS, "scale": scale})
    if not tk.loadData(musicxml):
        raise ScoreError("MusicXML を読み込めませんでした")
    return _substitute_missing_font(tk.renderToSVG(1))


def _bundled_font_bytes() -> bytes:
    return resources.files("utavideo").joinpath("templates", *_BUNDLED_FONT_TEMPLATE).read_bytes()


def svg_to_png(svg: str) -> bytes:
    """SVGをPNGにラスタライズする。"""
    with tempfile.NamedTemporaryFile(suffix=".otf") as font_file:
        font_file.write(_bundled_font_bytes())
        font_file.flush()
        png = resvg_py.svg_to_bytes(svg_string=svg, background="#ffffff", font_files=[font_file.name])
    return bytes(png)
