"""動作確認用の見本の曲フォルダを作る。

公開リポジトリに実際の曲は置けないので、確認したい要素（背景に負けない文字、歌詞と音の合い方、
位置を指定した行、はみ出す行、概要欄のクレジット）だけを持つ曲フォルダを作る。静止画の背景と
音源はリポジトリ作者本人が用意した素材を、楽譜（[inst.score]）は見本用に作成したオリジナルの
旋律（CC0）を同梱し、ループ動画・GIF・フォントはその場で合成する
（フォントは既定では環境に要求せず、--font に実在のフォント名を渡すと、そのフォントで描く）。

寸法は固定にする。座標もスタイルの大きさもここで一緒に作るので、--small で小さくしても
警告の出る行はそのまま警告が出る。
"""

from dataclasses import dataclass
from pathlib import Path

from utavideo import graph
from utavideo.config import PROJECT_CONFIG_NAME, OverlayText, Song
from utavideo.ffmpeg import run
from utavideo.project import SCAFFOLD_DIRS, ScaffoldResult, read_template_bytes, render_template
from utavideo.schema import schema_path

FONT_FAMILY = "Noto Sans JP"
FONT_DIR = Path("src/fonts")
FONT_FILE = FONT_DIR / "NotoSansJP-Regular.ttf"
FONT_LICENSE_FILE = FONT_DIR / "OFL.txt"
_FONT_TEMPLATE_DIR = "sample-fonts"
# 同梱フォントは既定の探索先に無いので、環境変数で渡してもらう（UTAVIDEO_FONT_DIRS は探索先を置き換える）。
# export にすると同じシェルで自分の曲に戻ったときにも効き続けるので、その場限りの形にする
FONT_DIRS_PREFIX = f"UTAVIDEO_FONT_DIRS={FONT_DIR.as_posix()}"
AUDIO_FILE = Path("src/mix/sample-v1.0.flac")
AUDIO_DURATION_S = 34  # 同梱の音源（AUDIO_FILE）の長さ。inst 用の音源もこれに揃える
AUDIO_INST_FILE = Path("src/mix/sample-inst-v1.0.flac")
VIDEO_BACKGROUND = Path("src/bg/loop.mp4")
STILL_BACKGROUND = Path("src/bg/still.jpg")
GIF_BACKGROUND = Path("src/bg/loop.gif")
LOGO_FILE = Path("src/layers/logo.png")  # [[layers]] の見本（合成、半透明の帯）
LOGO_COLOR = "0xFF6FA5"
AVATAR_FILE = Path("src/avatar/avatar-raw.mp4")  # [avatar] の見本（合成、青一色の上を図形が動く）
AVATAR_SIZE = (480, 270)
AVATAR_FPS = 15
AVATAR_COLOR = "0x0000ff"  # ブルーバック（[avatar] の既定と同じ）
AVATAR_SHAPE_COLOR = "0xFFFFFF"  # 動く図形（キー抜きで残る被写体の代わり）
# 録画は音源より AVATAR_LEAD_S 秒早く始まり、AVATAR_TAIL_S 秒長く続く（sync = "auto" の正解値）
AVATAR_LEAD_S = 2
AVATAR_TAIL_S = 1
LYRICS_FILE = Path("src/lyrics.ass")
_MATERIAL_TEMPLATE_DIR = "sample-materials"
_MATERIAL_CREDIT = "Kana Nagata（背景: VRoid Studio で制作・VRM Posing Desktop で撮影 / 音源: 作曲）"
SCORE_FILE = Path("src/score.mscz")  # [inst.score] の見本（issue #147）
_SCORE_TEMPLATE_DIR = "sample-score"
_SCORE_CREDIT = "utavideo（見本用に作成したオリジナルの旋律。CC0 1.0）"

# 1920x1080 を基準にして、--small では全部を同じ比率で縮める
BASE_SIZE = (1920, 1080)
SMALL_SIZE = (640, 360)
# 同梱の音源（src/mix/sample-v1.0.flac）は 34 秒。sample-lyrics.ass の行はこの中に収める
# （はみ出すと検査の警告が増え、テストが落ちる）
LOOP_S = 5  # 背景が1周する秒数。34 秒の間に 6 周と少しするので、繰り返しを確かめられる
GIF_SIZE = (480, 270)
GIF_FPS = 8
GIF_S = 2
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
            render_template(
                "sample-README.md",
                font_note=font_note(font),
                material_note=material_note(),
                prefix=command_prefix(font),
            ),
        ),
    ]
    created += _materials(root, spec)
    created.append(_install_asset(root, _SCORE_TEMPLATE_DIR, SCORE_FILE, "score.mscz"))
    if font is None:
        created += [
            _install_asset(root, _FONT_TEMPLATE_DIR, path, path.name)
            for path in (FONT_FILE, FONT_LICENSE_FILE)
        ]
    return ScaffoldResult(created=created)


def _install_asset(root: Path, template_dir: str, dest: Path, source_name: str) -> Path:
    """templates/<template_dir>/ のファイルを曲フォルダにコピーする。"""
    return _write_bytes(root / dest, read_template_bytes(template_dir, source_name))


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
        schema=schema_path().as_uri(),
        title=_SONG.title,
        slug=_SONG.slug,
        artist=_SONG.artist,
        label=_SONG.label,
        singer=_SINGER,
        overlay_text=_OVERLAY_TEXT,
        audio=AUDIO_FILE.as_posix(),
        inst_audio=AUDIO_INST_FILE.as_posix(),
        background=VIDEO_BACKGROUND.as_posix(),
        still=STILL_BACKGROUND.as_posix(),
        gif=GIF_BACKGROUND.as_posix(),
        avatar=AVATAR_FILE.as_posix(),
        logo=LOGO_FILE.as_posix(),
        score=SCORE_FILE.as_posix(),
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
        lyrics_size=str(spec.px(110)),
        lyrics_spacing=str(spec.px(2)),
        lyrics_outline=str(spec.px(2)),
        lyrics_margin=str(spec.px(120)),
        lyrics_marginv=str(spec.px(90)),
        comment_size=str(spec.px(48)),
        outline=str(spec.px(1)),
        comment_margin=str(spec.px(60)),
        title_size=str(spec.px(40)),
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


def material_note() -> str:
    """背景の静止画・音源・楽譜についての説明（出所）。"""
    return (
        f"背景の静止画（`{STILL_BACKGROUND.as_posix()}`）と音源（`{AUDIO_FILE.as_posix()}`）は、"
        f"{_MATERIAL_CREDIT}によるものです。楽譜（`{SCORE_FILE.as_posix()}`）は"
        f"{_SCORE_CREDIT}によるものです（`utavideo inst` の楽譜表示を試すための見本で、"
        "音源そのものの旋律とは一致しません）。ループする背景"
        f"（`{VIDEO_BACKGROUND.as_posix()}`・`{GIF_BACKGROUND.as_posix()}`）、"
        f"[[layers]] の見本（`{LOGO_FILE.as_posix()}`）、"
        f"[avatar] の見本（`{AVATAR_FILE.as_posix()}`）、"
        f"inst 用の音源（`{AUDIO_INST_FILE.as_posix()}`）、"
        "フォント以外の合成音は、その場で合成したものです。"
    )


def _materials(root: Path, spec: _Spec) -> list[Path]:
    # 4:3（動画と縦横比が違う）の実素材。fit の切り取り・余白の効き方や、
    # 実際の絵の上での文字の読みやすさが目で分かる
    audio = _install_asset(root, _MATERIAL_TEMPLATE_DIR, AUDIO_FILE, "audio.flac")
    still = _install_asset(root, _MATERIAL_TEMPLATE_DIR, STILL_BACKGROUND, "still.jpg")

    # inst（歌唱練習用の動画）用の、声を抜いた伴奏の代わり。本編と別ファイルなことが分かればよいので、
    # 実素材ではなく音源と聞き分けやすいサイン波を合成する（inst.audio が効いていることを耳で確かめられる）
    inst_audio = root / AUDIO_INST_FILE
    _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=220:duration={AUDIO_DURATION_S}"], inst_audio)

    # カラーバー ＋ 1周で横断する白い箱
    loop = root / VIDEO_BACKGROUND
    _ffmpeg(
        [*_box_over_bars(spec.size, spec.fps, LOOP_S),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p"],
        loop,
    )  # fmt: skip
    gif = root / GIF_BACKGROUND
    _ffmpeg(_box_over_bars(GIF_SIZE, GIF_FPS, GIF_S, extra_filters=_GIF_PALETTE), gif)

    # [[layers]] の見本。半透明の帯（アルファ付き PNG）。実際の素材はユーザーが画像編集ソフト等で作る
    logo = root / LOGO_FILE
    w, h = spec.px(320), spec.px(120)
    _ffmpeg(
        ["-f", "lavfi", "-i", f"color=c={LOGO_COLOR}:s={w}x{h}:d=1,format=rgba,colorchannelmixer=aa=0.85",
         "-frames:v", "1", "-update", "1", "-c:v", "png"],
        logo,
    )  # fmt: skip

    avatar = _avatar_video(root, audio)
    return [audio, still, inst_audio, loop, gif, logo, avatar]


def _avatar_video(root: Path, audio: Path) -> Path:
    """[avatar] の見本。実写のブルーバック録画は用意できないので、青一色の上を図形が動く映像を合成する。

    sync = "auto" が実際に相互相関で求まることを確かめられるよう、録画の音声には見本の音源
    （audio）そのものを AVATAR_LEAD_S 秒遅らせて入れる（頭出しの正解値が既知になる）。
    """
    output = root / AVATAR_FILE
    total = AVATAR_LEAD_S + AUDIO_DURATION_S + AVATAR_TAIL_S
    w, h = AVATAR_SIZE
    box = max(2, round(w / 4))
    filter_complex = (
        f"[0:v][1:v]overlay=x=(W-w)*t/{total}:y=(H-h)/2[v];"
        f"[2:a]atrim=0:{AVATAR_LEAD_S}[lead];"
        f"[3:a]atrim=0:{AUDIO_DURATION_S}[song];"
        f"[2:a]atrim=0:{AVATAR_TAIL_S}[tail];"
        "[lead][song][tail]concat=n=3:v=0:a=1[a]"
    )
    _ffmpeg(
        ["-f", "lavfi", "-i", f"color=c={AVATAR_COLOR}:s={w}x{h}:r={AVATAR_FPS}:d={total}",
         "-f", "lavfi", "-i", f"color=c={AVATAR_SHAPE_COLOR}:s={box}x{box}:r={AVATAR_FPS}:d={total}",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-i", str(audio),
         "-filter_complex", filter_complex,
         "-map", "[v]", "-map", "[a]", "-t", str(total),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p", "-c:a", "aac"],
        output,
    )  # fmt: skip
    return output


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
