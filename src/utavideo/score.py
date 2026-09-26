"""MuseScore の楽譜 (.mscz) を横1段のPNGに描く。

.mscz → MusicXML（MuseScore CLI）→ 横1段のSVG（Verovio）→ PNG（resvg-py）の順に変換する。
音源との同期・ffmpegへの統合・inst コマンドへの組み込みはここでは扱わない。
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import resvg_py
import verovio

from utavideo.errors import UtavideoError


class ScoreError(UtavideoError):
    """MuseScore CLI が見つからない、または楽譜を描けなかった。"""


_MUSESCORE_NAMES = ("mscore", "musescore4", "MuseScore4", "mscore4portable")
# Homebrew等でPATHに入らないことが多いmacOSのアプリバンドル内バイナリ
_MACOS_APP_PATH = Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore")


def find_musescore() -> str | None:
    """MuseScore 4 の実行ファイルを探す。見つからなければ None。"""
    if env := os.environ.get("UTAVIDEO_MUSESCORE"):
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
            "環境変数 UTAVIDEO_MUSESCORE に実行ファイルのパスを指定してください"
        )
    return musescore


def _run_musescore_export(
    musescore: str, input_path: Path, out_path: Path, *, transpose_interval: int | None = None
) -> None:
    """MuseScore CLIで input_path を out_path（拡張子で書式が決まる）に書き出す。

    transpose_interval を渡すと、書き出す前にその分だけ移調する（0以上25以下、実測で
    半音±12相当。範囲外の値は書き出し先ファイルが作られないまま黙って失敗する）。
    """
    args = [musescore]
    if transpose_interval is not None:
        options = {
            "mode": "by_interval",
            "direction": "up" if transpose_interval >= 0 else "down",
            "transposeInterval": abs(transpose_interval),
            "transposeKeySignatures": True,
            "transposeChordNames": True,
        }
        args += ["--transpose", json.dumps(options)]
    args += ["-o", str(out_path), str(input_path)]
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors="replace")
    except OSError as e:
        raise ScoreError(f"{musescore} を実行できません: {e}") from e
    if result.returncode != 0 or not out_path.exists():
        tail = (result.stderr.strip() or result.stdout.strip())[-500:]
        raise ScoreError(f"MuseScore での書き出しに失敗しました: {tail}")


# MuseScore CLIの--transposeのtransposeIntervalは半音に線形対応しないので実測で対応表を作った
# （検証: issue #144。docs/verification/20260927-transpose-interval-mapping.md）。1回のtransposeで
# 移調できるのは1オクターブ分（実測で半音±12相当、transposeInterval 0〜25）までなので、
# 1オクターブを超える分は_FULL_OCTAVE_INTERVAL（半音12相当）を繰り返し適用して稼ぐ
# （divmod(semitones, 12)の余りは常に0〜11なので、この表に半音12のキーは無い）。
_FULL_OCTAVE_INTERVAL = 25
_SEMITONE_TO_INTERVAL = {0: 0, 1: 3, 2: 4, 3: 7, 4: 8, 5: 11, 6: 12, 7: 14, 8: 17, 9: 18, 10: 21, 11: 22}


def to_musicxml(mscz_path: Path, musescore: str, *, semitones: int = 0) -> str:
    """.mscz を MusicXML に変換して読む（元のファイルは書き換えない）。

    semitones を指定すると、その半音数だけ移調してから変換する（--keysとの連動。issue #144）。
    調号・臨時記号の♯系/♭系のスペリング判断はMuseScore側に任せ、utavideoでは行わない。
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        current = mscz_path
        octaves, remainder = divmod(semitones, 12)
        for i in range(abs(octaves)):
            step_out = Path(tmp_dir) / f"octave{i}.mscz"
            interval = _FULL_OCTAVE_INTERVAL if octaves > 0 else -_FULL_OCTAVE_INTERVAL
            _run_musescore_export(musescore, current, step_out, transpose_interval=interval)
            current = step_out
        out_path = Path(tmp_dir) / "score.musicxml"
        interval = _SEMITONE_TO_INTERVAL[remainder] if remainder else None
        _run_musescore_export(musescore, current, out_path, transpose_interval=interval)
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
_SMUFL_PRIVATE_USE_AREA = re.compile("[\ue000-\uf8ff]")
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


@dataclass(frozen=True)
class NoteEvent:
    """1音符（和音は1まとめ）の、譜面上のx座標(px)と発音時刻(1小節目の頭を0秒とした秒)。"""

    x: float
    time_s: float


_BBOX_RENDER_OPTIONS = {**_RENDER_OPTIONS, "svgBoundingBoxes": True}
_BBOX_GROUP = re.compile(r"<g\b([^>]*)>\s*(<rect\b[^>]*/>)")
_ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')


def _parse_note_bboxes(svg: str, scale: int) -> dict[str, float]:
    """音符ごとのbboxから、譜面上のx座標(中心、実際に描かれるPNGと同じピクセル単位)を取り出す。

    bboxの座標はSVG内側の<svg>要素のviewBox（Verovioの内部単位）で書かれており、外側の<svg>の
    width（実際に書き出されるピクセル数）とは異なる縮尺になっている。実測では
    viewBox単位 / ピクセル = 1000 / scale だったので、その逆数を掛けてピクセル単位に直す
    （検証: issue #142。render_horizontal_svgが返すSVG自体はresvg-pyがviewBoxを見て正しく
    ラスタライズするので影響しないが、bboxの数値を直接読むnote_eventsだけこの変換が要る）。
    """
    x_by_note_id: dict[str, float] = {}
    for group_attrs, rect_tag in _BBOX_GROUP.findall(svg):
        attrs = dict(_ATTR.findall(group_attrs))
        note_id = attrs.get("id", "")
        if attrs.get("class") != "note bounding-box" or not note_id.startswith("bbox-"):
            continue
        rect_attrs = dict(_ATTR.findall(rect_tag))
        x = (float(rect_attrs["x"]) + float(rect_attrs["width"]) / 2) * scale / 1000
        x_by_note_id[note_id.removeprefix("bbox-")] = x
    return x_by_note_id


def note_events(musicxml: str, *, scale: int = 40) -> list[NoteEvent]:
    """音符ごとの、譜面上のx座標と発音時刻を対応づける。

    発音時刻はVerovioのタイムマップ計算（MusicXMLの`<sound tempo>`）に従う。テンポ変化・
    拍子変化・♩=♩.のようなテンポの読み替えを反映する。rit.のような連続的なテンポ変化は、
    `<words>rit.</words>`のような自由テキストとしてしか入らずプログラムから読み取れないので
    使わない。MuseScoreは、その付近に`<sound tempo>`で（滑らかな曲線ではなく段階的な近似
    ではあるが）実効テンポを一緒に書き出すことが多く、その場合はタイムマップに反映される
    （検証: issue #141）。

    和音は同時に鳴る全音符が同じ発音時刻になるので、1つの点にまとめる。休符には発音時刻が
    無いため、その前後の音符を結ぶ直線で近似することになる。

    表示用の画像（`render_horizontal_svg`）と組み合わせるときは、同じ`scale`を渡すこと
    （座標系がずれる）。
    """
    tk = verovio.toolkit()
    tk.setOptions({**_BBOX_RENDER_OPTIONS, "scale": scale})
    if not tk.loadData(musicxml):
        raise ScoreError("MusicXML を読み込めませんでした")
    x_by_note_id = _parse_note_bboxes(tk.renderToSVG(1), scale)

    xs_by_time_ms: dict[float, list[float]] = {}
    for entry in tk.renderToTimemap():
        for note_id in entry.get("on", ()):
            if (x := x_by_note_id.get(note_id)) is not None:
                xs_by_time_ms.setdefault(entry["tstamp"], []).append(x)

    events = [NoteEvent(x=sum(xs) / len(xs), time_s=time_ms / 1000) for time_ms, xs in xs_by_time_ms.items()]
    events.sort(key=lambda e: e.time_s)
    return events


def _bundled_font_bytes() -> bytes:
    return resources.files("utavideo").joinpath("templates", *_BUNDLED_FONT_TEMPLATE).read_bytes()


def svg_to_png(svg: str) -> bytes:
    """SVGをPNGにラスタライズする。"""
    # resvg-py（ネイティブ拡張）にパスで渡して読ませるため、開いたハンドルを持ったままでは
    # 別ハンドルから再オープンできないWindowsの制約を避け、閉じてから渡す（delete=Falseで
    # クローズ時に消えないようにし、読み終えたら明示的に消す）
    with tempfile.NamedTemporaryFile(suffix=".otf", delete=False) as font_file:
        font_file.write(_bundled_font_bytes())
        font_path = font_file.name
    try:
        png = resvg_py.svg_to_bytes(svg_string=svg, background="#ffffff", font_files=[font_path])
    finally:
        Path(font_path).unlink()
    return bytes(png)


@dataclass(frozen=True)
class RenderedScore:
    """.mscz から作った、横1段のPNG（png・width・height）と、音符ごとのx・発音時刻（events）。"""

    png: bytes
    width: int
    height: int
    events: list[NoteEvent]


_SVG_SIZE = re.compile(r'<svg width="(\d+)px" height="(\d+)px"')


def render(mscz_path: Path, musescore: str, *, scale: int = 40, semitones: int = 0) -> RenderedScore:
    """.mscz → MusicXML → 横1段のPNG・音符イベントを一度に作る（MusicXMLへの変換を1回で済ませる）。

    semitones は `to_musicxml` に渡す（--keysとの連動。issue #144）。
    """
    musicxml = to_musicxml(mscz_path, musescore, semitones=semitones)
    svg = render_horizontal_svg(musicxml, scale=scale)
    size = _SVG_SIZE.match(svg)
    if size is None:
        raise ScoreError("SVGの大きさ（width・height）を読み取れませんでした")
    width, height = int(size.group(1)), int(size.group(2))
    return RenderedScore(
        png=svg_to_png(svg), width=width, height=height, events=note_events(musicxml, scale=scale)
    )
