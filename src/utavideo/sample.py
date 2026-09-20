"""動作確認用の見本の曲フォルダを作る。素材（フォント・音源・背景）はその場で合成する。

公開リポジトリに実際の曲は置けないので、確認したい要素（ループする背景、位置を指定した行、
はみ出す行、概要欄のクレジット）だけを持つ曲フォルダを合成する。フォントも合成するため、
既定では環境にフォントを要求しない（--font に実在のフォント名を渡すと、そのフォントで描く）。

寸法と長さは固定にする。座標もスタイルの大きさもここで一緒に作るので、--small で小さくしても
警告の出る行はそのまま警告が出る。
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pysubs2
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from utavideo import graph, subs
from utavideo.config import PROJECT_CONFIG_NAME
from utavideo.ffmpeg import run
from utavideo.project import SCAFFOLD_DIRS, ScaffoldResult, render_template

FONT_FAMILY = "Utavideo Sample"
FONT_DIR = Path("src/fonts")
FONT_FILE = FONT_DIR / "UtavideoSample.ttf"
# 合成フォントは既定の探索先に無いので、環境変数で渡してもらう（UTAVIDEO_FONT_DIRS は探索先を置き換える）
FONT_DIRS_EXPORT = f'export UTAVIDEO_FONT_DIRS="$PWD/{FONT_DIR.as_posix()}"'
AUDIO_FILE = Path("src/mix/sample-v1.0.flac")
VIDEO_BACKGROUND = Path("src/bg/loop.mp4")
STILL_BACKGROUND = Path("src/bg/still.png")
GIF_BACKGROUND = Path("src/bg/loop.gif")
LYRICS_FILE = Path("src/lyrics.ass")

# 1920x1080 を基準にして、--small では全部を同じ比率で縮める
BASE_SIZE = (1920, 1080)
SMALL_SIZE = (640, 360)
# 音源の長さ。sample-lyrics.ass の行はこの中に収める（はみ出すと検査の警告が増え、テストが落ちる）
DURATION_S = 36
LOOP_S = 5  # 背景が1周する秒数。36 秒の間に 7 周と少しするので、繰り返しを確かめられる
GIF_SIZE = (480, 270)
GIF_FPS = 8
GIF_S = 2

# 曲名表示（overlay_text.text）に入る文字。合成フォントに字形を入れるために要る
_TITLE = "見本のうた"
_ARTIST = "架空アーティスト"


@dataclass(frozen=True)
class _Spec:
    size: tuple[int, int]
    fps: int
    crf: int
    preset: str
    font: str

    def px(self, base: int) -> int:
        """1920x1080 のときの px を、この見本の寸法に合わせる。"""
        return round(base * self.size[0] / BASE_SIZE[0])


def build_box_font(
    path: Path, family: str, *, chars: Iterable[str], advance: int = 1000, space_advance: int = 500
) -> Path:
    """どの文字も塗りつぶしの四角になる TrueType フォントを作る（見本とテストの共通部品）。

    字形を持たない文字は別のフォントで代替されて環境ごとに絵が変わるので、使う文字はすべて
    cmap に入れる。送り幅は全部同じなので、はみ出しの概算は文字数に比例する。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    codes = sorted({ord(ch) for ch in chars} - {0x20})
    names = {code: f"c{code:04X}" for code in codes}
    box = _box(advance)
    fb = FontBuilder(unitsPerEm=1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "space", *names.values()])
    fb.setupCharacterMap({0x20: "space", **names})
    fb.setupGlyf({".notdef": box, "space": TTGlyphPen(None).glyph(), **{n: box for n in names.values()}})
    fb.setupHorizontalMetrics(
        {".notdef": (advance, 0), "space": (space_advance, 0), **{n: (advance, 0) for n in names.values()}}
    )
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    fb.save(str(path))
    return path


def _box(advance: int):
    left, right = round(advance * 0.1), round(advance * 0.9)
    pen = TTGlyphPen(None)
    pen.moveTo((left, 0))
    pen.lineTo((left, 700))
    pen.lineTo((right, 700))
    pen.lineTo((right, 0))
    pen.closePath()
    return pen.glyph()


def create(root: Path, *, font: str | None = None, small: bool = False) -> ScaffoldResult:
    """見本の曲フォルダを作り、作ったファイルを返す。root は存在しないパス。"""
    spec = _Spec(
        size=SMALL_SIZE if small else BASE_SIZE,
        fps=10 if small else 30,
        crf=30 if small else 18,
        preset="ultrafast" if small else "medium",
        font=font or FONT_FAMILY,
    )
    for rel in SCAFFOLD_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)

    lyrics = _lyrics(spec)
    created = [
        _write(root / PROJECT_CONFIG_NAME, _config(spec)),
        _write(root / LYRICS_FILE, lyrics),
        _write(root / "README.md", render_template("sample-README.md", font_note=font_note(font))),
    ]
    if font is None:
        created.append(build_box_font(root / FONT_FILE, FONT_FAMILY, chars=_drawn_text(lyrics)))
    created += _materials(root, spec)
    return ScaffoldResult(created=created)


def _drawn_text(lyrics: str) -> str:
    """画面に出る文字だけ（上書きタグを除いた歌詞の行と、曲名表示）。合成フォントの字形を決める。"""
    script = pysubs2.SSAFile.from_string(lyrics, format_="ass")
    drawn = "".join(subs.OVERRIDE_BLOCK.sub("", event.text) for event in subs.dialogues(script))
    return drawn.replace(r"\N", "") + _TITLE + _ARTIST


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _config(spec: _Spec) -> str:
    return render_template(
        "sample.toml",
        title=_TITLE,
        artist=_ARTIST,
        audio=AUDIO_FILE.as_posix(),
        background=VIDEO_BACKGROUND.as_posix(),
        still=STILL_BACKGROUND.as_posix(),
        gif=GIF_BACKGROUND.as_posix(),
        width=str(spec.size[0]),
        height=str(spec.size[1]),
        fps=str(spec.fps),
        crf=str(spec.crf),
        preset=spec.preset,
    )


def _lyrics(spec: _Spec) -> str:
    w, h = spec.size
    return render_template(
        "sample-lyrics.ass",
        font=spec.font,
        width=str(w),
        height=str(h),
        lyrics_size=str(spec.px(100)),
        lyrics_outline=str(spec.px(4)),
        lyrics_margin=str(spec.px(120)),
        lyrics_marginv=str(spec.px(90)),
        comment_size=str(spec.px(44)),
        outline=str(spec.px(3)),
        comment_margin=str(spec.px(60)),
        title_size=str(spec.px(36)),
        title_margin=str(spec.px(40)),
        title_marginv=str(spec.px(30)),
        move_x1=str(round(w * 0.125)),
        move_x2=str(round(w * 0.875)),
        move_y=str(round(h * 5 / 6)),
        pos_x=str(round(w / 2)),
        pos_y=str(round(h * 5 / 18)),
    )


def font_note(font: str | None) -> str:
    """歌詞のフォントについての説明。合成フォントのときは、その場所を渡す環境変数も。"""
    if font is not None:
        return f"歌詞には実在のフォント {font} を使います。"
    return (
        "歌詞のフォントも合成してあるので、この曲フォルダでコマンドを実行する前に、"
        "その場所を渡してください（渡している間は自分のフォントが見つかりません）。\n\n"
        f"```sh\n{FONT_DIRS_EXPORT}\n```"
    )


def _materials(root: Path, spec: _Spec) -> list[Path]:
    w, h = spec.size
    # 4 秒ごとに高さの変わる合成音。どこを切り出したか・どこでフェードしたかが耳で分かる
    tone = "0.25*sin(2*PI*220*(1+floor(t/4)-3*floor(t/12))*t)"
    audio = root / AUDIO_FILE
    _ffmpeg(["-f", "lavfi", "-i", f"aevalsrc={tone}:d={DURATION_S}:s=48000", "-ac", "1"], audio)

    # カラーバー（平らな色の面なので切り取り・拡大の効き方が分かる）＋ 1周で横断する白い箱
    bars = root / STILL_BACKGROUND
    _ffmpeg(["-f", "lavfi", "-i", f"smptebars=size={w}x{h}", "-frames:v", "1"], bars)
    loop = root / VIDEO_BACKGROUND
    _ffmpeg(
        [*_box_over_bars(spec.size, spec.fps, LOOP_S),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p"],
        loop,
    )  # fmt: skip
    gif = root / GIF_BACKGROUND
    _ffmpeg(_box_over_bars(GIF_SIZE, GIF_FPS, GIF_S), gif)
    return [audio, bars, loop, gif]


def _box_over_bars(size: tuple[int, int], fps: int, seconds: int) -> list[str]:
    w, h = size
    box = max(2, round(w / 16))
    return [
        "-f", "lavfi", "-i", f"smptebars=size={w}x{h}:rate={fps}:duration={seconds}",
        "-f", "lavfi", "-i", f"color=c=white:size={box}x{box}:rate={fps}:duration={seconds}",
        "-filter_complex", f"[0:v][1:v]overlay=x=(W-w)*t/{seconds}:y=(H-h)/2[v]",
        "-map", "[v]",
    ]  # fmt: skip


def _ffmpeg(args: list[str], output: Path) -> None:
    run(["ffmpeg", *graph.QUIET, *args], output, total_s=0)
