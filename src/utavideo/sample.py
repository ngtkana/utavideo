"""動作確認用の見本の曲フォルダを作る。フォント以外の素材（音源・背景）はその場で合成する。

公開リポジトリに実際の曲は置けないので、確認したい要素（ループする背景、位置を指定した行、
はみ出す行、概要欄のクレジット）だけを持つ曲フォルダを合成する。フォントは Noto Sans JP を
同梱するため、既定では環境にフォントを要求しない（--font に実在のフォント名を渡すと、その
フォントで描く）。

寸法と長さは固定にする。座標もスタイルの大きさもここで一緒に作るので、--small で小さくしても
警告の出る行はそのまま警告が出る。
"""

from dataclasses import dataclass
from pathlib import Path

from utavideo import graph
from utavideo.config import PROJECT_CONFIG_NAME, OverlayText, Song
from utavideo.ffmpeg import run
from utavideo.project import SCAFFOLD_DIRS, ScaffoldResult, read_template_bytes, render_template

FONT_FAMILY = "Noto Sans JP"
FONT_DIR = Path("src/fonts")
FONT_FILE = FONT_DIR / "NotoSansJP-Regular.ttf"
FONT_LICENSE_FILE = FONT_DIR / "OFL.txt"
_FONT_TEMPLATE_DIR = "sample-fonts"
# 同梱フォントは既定の探索先に無いので、環境変数で渡してもらう（UTAVIDEO_FONT_DIRS は探索先を置き換える）。
# export にすると同じシェルで自分の曲に戻ったときにも効き続けるので、その場限りの形にする
FONT_DIRS_PREFIX = f"UTAVIDEO_FONT_DIRS={FONT_DIR.as_posix()}"
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
# 静止画の背景だけ 4:3 にする。動画と縦横比が違わないと、fit の cover（切り取り）と
# contain（余白）がどちらも何もしないので、差し替えても見た目が変わらない
STILL_ASPECT = 4 / 3
# GIF は 256 色までなので、既定のエンコーダに任せるとカラーバーの平らな面がディザの市松模様になる。
# 出てくる色を数えたパレットを作り、ディザ無しで割り当てる（色の潰れが背景の見え方に混ざらない）
_GIF_PALETTE = ",split[a][b];[a]palettegen=max_colors=32[p];[b][p]paletteuse=dither=none"

# 見本の曲（架空）。utavideo.toml をここから作る
_SONG = Song(title="見本のうた", slug="sample", artist="架空アーティスト", label="utavideo 見本")
_SINGER = "架空シンガー"  # 歌った人（song.artist は原曲の人）
_OVERLAY_TEXT = OverlayText().text  # 曲名表示（画面に出る）


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
        _write(
            root / "README.md",
            render_template("sample-README.md", font_note=font_note(font), prefix=command_prefix(font)),
        ),
    ]
    created += _materials(root, spec)
    if font is None:
        created += [_install_font_asset(root, path) for path in (FONT_FILE, FONT_LICENSE_FILE)]
    return ScaffoldResult(created=created)


def _install_font_asset(root: Path, path: Path) -> Path:
    """templates/sample-fonts/ の同名ファイルを曲フォルダにコピーする。"""
    return _write_bytes(root / path, read_template_bytes(_FONT_TEMPLATE_DIR, path.name))


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _config(spec: _Spec) -> str:
    return render_template(
        "sample.toml",
        title=_SONG.title,
        slug=_SONG.slug,
        artist=_SONG.artist,
        label=_SONG.label,
        singer=_SINGER,
        overlay_text=_OVERLAY_TEXT,
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
        lyrics_spacing=str(spec.px(2)),
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


def command_prefix(font: str | None) -> str:
    """同梱フォントのときに、コマンドの前に付ける環境変数（末尾の空白を含む）。"""
    return "" if font is not None else f"{FONT_DIRS_PREFIX} "


def font_note(font: str | None) -> str:
    """歌詞のフォントについての説明。同梱フォントのときは、その場所の渡し方も。"""
    if font is not None:
        return f"歌詞には実在のフォント {font} を使います。"
    return (
        "歌詞のフォントには Noto Sans JP（SIL Open Font License、"
        f"`{FONT_LICENSE_FILE.as_posix()}` に全文を同梱）を使います。"
        "この曲フォルダで実行するコマンドの前に "
        f"`{FONT_DIRS_PREFIX}` を付けて、その場所を渡します"
        "（`UTAVIDEO_FONT_DIRS` は探す場所を置き換えるので、自分の曲に戻るときは付けません）。"
    )


def _materials(root: Path, spec: _Spec) -> list[Path]:
    h = spec.size[1]
    # 4 秒ごとに 220Hz ずつ高くなる合成音。36 秒で 9 段すべて違う高さになるので、
    # どこを切り出したか・どこでフェードしたかが耳で分かる（繰り返すと区別できない）
    tone = "0.25*sin(2*PI*220*(1+floor(t/4))*t)"
    audio = root / AUDIO_FILE
    _ffmpeg(["-f", "lavfi", "-i", f"aevalsrc={tone}:d={DURATION_S}:s=48000", "-ac", "1"], audio)

    # カラーバーの静止画。動画と縦横比が違うので、fit の切り取り・余白の効き方が目で分かる
    bars = root / STILL_BACKGROUND
    still_w = round(h * STILL_ASPECT)
    _ffmpeg(["-f", "lavfi", "-i", f"smptebars=size={still_w}x{h}", "-frames:v", "1"], bars)
    # カラーバー ＋ 1周で横断する白い箱
    loop = root / VIDEO_BACKGROUND
    _ffmpeg(
        [*_box_over_bars(spec.size, spec.fps, LOOP_S),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p"],
        loop,
    )  # fmt: skip
    gif = root / GIF_BACKGROUND
    _ffmpeg(_box_over_bars(GIF_SIZE, GIF_FPS, GIF_S, extra_filters=_GIF_PALETTE), gif)
    return [audio, bars, loop, gif]


def _box_over_bars(size: tuple[int, int], fps: int, seconds: int, *, extra_filters: str = "") -> list[str]:
    """カラーバーの上を白い箱が1周する映像の入力。extra_filters は出力ラベルの前に足す。"""
    w, h = size
    box = max(2, round(w / 16))
    return [
        "-f", "lavfi", "-i", f"smptebars=size={w}x{h}:rate={fps}:duration={seconds}",
        "-f", "lavfi", "-i", f"color=c=white:size={box}x{box}:rate={fps}:duration={seconds}",
        "-filter_complex", f"[0:v][1:v]overlay=x=(W-w)*t/{seconds}:y=(H-h)/2{extra_filters}[v]",
        "-map", "[v]",
    ]  # fmt: skip


def _ffmpeg(args: list[str], output: Path) -> None:
    run(["ffmpeg", *graph.QUIET, *args], output, total_s=0)
