"""[avatar]（ブルーバック・グリーンバックで録画したアバター動画の合成）。issue #112。

撮影後にやることは3つ: 1) クロマキー、2) 位置と大きさ、3) タイミング（音の頭出しは自動、動きの
遅延は手入力）。1)・3) の元になる値（file・key・similarity・despill・sync・delay_ms）は
「答えが一つに決まるもの」として、build/.work/ にキー抜き・頭出し済みの中間動画をキャッシュする
（utavideo avatar prepare のような手動コマンドは作らない。build・check 等が自動で判定する）。
2) の値（scale・anchor・margin・layer）は「気分で変えたいもの」として、[[layers]]
（utavideo.layers）と同じ graph.LayerSpec に変換し、同じ合成コードにそのまま乗せる
（別の合成経路は新設しない）。
"""

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from utavideo import graph, layers, subs
from utavideo.config import Avatar
from utavideo.console import err_console
from utavideo.ffmpeg import FFmpegError, probe_audio, run, write_text
from utavideo.project import Project

# 頭出しの相互相関に使うサンプルレート。音声の相互相関には粗くて足りる（issue #112）
SAMPLE_RATE = 8000
# z 値（(peak - mean) / std）の際立ちの目安（issue #112）。5 未満は自動推定を信頼できないのでエラー、
# 10 未満は警告に留める
Z_ERROR_BELOW = 5.0
Z_WARNING_BELOW = 10.0

_CACHE_FORMAT = 1
_PREPARED_NAME = "avatar-prepared.mov"
_CACHE_NAME = "avatar-cache.json"
_COLORKEY_BLEND = 0.0  # 今回は固定値（issue #112 の「決定」）


def file_path(root: Path, avatar: Avatar) -> Path:
    """[[layers]] の layers.file_path と同じ考え方（相対パスは曲フォルダから）。"""
    file = avatar.file
    return file if file.is_absolute() else root / file


# --- 検査（ファイルの有無・形式、sync = "auto" の際立ち） -----------------------------------


@dataclass(frozen=True)
class SyncResult:
    """頭出しの結果。z は sync が数値（手動）のときは None。"""

    offset_s: float
    z: float | None


@dataclass(frozen=True)
class AvatarAnalysis:
    issues: list[subs.Issue]
    sync: SyncResult | None  # avatar が無い、またはファイルの検査で先に止まったときは None


def analyze(project: Project) -> AvatarAnalysis:
    """[avatar] の検査と、あれば頭出しの結果。avatar が無い曲では issues も sync も空。"""
    avatar = project.config.avatar
    if avatar is None:
        return AvatarAnalysis([], None)
    path = file_path(project.root, avatar)
    if not path.is_file():
        return AvatarAnalysis([subs.Issue("error", f"file のファイルがありません: {path}")], None)
    ext = path.suffix.lower()
    if ext not in graph.ANIMATED_EXTS:
        return AvatarAnalysis([subs.Issue("error", f"file の形式に対応していません: {ext}")], None)
    if not isinstance(avatar.sync, str):  # 手動オフセット（秒）。録画の音声は要らない
        return AvatarAnalysis([], SyncResult(float(avatar.sync), None))
    info = probe_audio(path)
    if not info.has_sound:
        message = 'sync = "auto" には録画（file）の音声が要ります（無ければ sync に秒数を直接書きます）'
        return AvatarAnalysis([subs.Issue("error", message)], None)
    if not project.audio_path.is_file():
        # audio.file 自体が無いことは analyze.audio_issues が別に報告するので、ここでは頭出しをしない
        return AvatarAnalysis([], None)
    result = resolve_sync(project, avatar, path)
    return AvatarAnalysis(sync_issues(result), result)


def sync_issues(result: SyncResult) -> list[subs.Issue]:
    if result.z is None:  # 手動指定
        return []
    if result.z < Z_ERROR_BELOW:
        message = (
            f'sync = "auto" の際立ちが低すぎます（z = {result.z:.1f}）。'
            f"求めたズレ（{result.offset_s:.3f} 秒）を信頼できないので、"
            "sync に秒数を直接書いて手動で指定してください"
        )
        return [subs.Issue("error", message)]
    if result.z < Z_WARNING_BELOW:
        message = (
            f'sync = "auto" の際立ちが低めです（z = {result.z:.1f}、'
            f"ズレ {result.offset_s:.3f} 秒）。誤りがないか確認してください"
        )
        return [subs.Issue("warning", message)]
    return []


# --- 頭出し（録画の音声と音源の相互相関） --------------------------------------------------


def _read_mono_pcm(path: Path) -> np.ndarray:
    """path の音声を SAMPLE_RATE Hz・モノラルの PCM（-1.0〜1.0 の float32）にして読む。"""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    args = [
        ffmpeg, *graph.QUIET,
        "-i", str(path),
        "-vn", "-map", "0:a:0",
        "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-f", "s16le", "-",
    ]  # fmt: skip
    try:
        out = subprocess.run(args, capture_output=True)
    except OSError as e:
        raise FFmpegError(f"{ffmpeg} を実行できません: {e}") from e
    if out.returncode != 0:
        detail = out.stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise FFmpegError(f"{path} の音声を読めません（終了コード {out.returncode}）: {detail}")
    return np.frombuffer(out.stdout, dtype="<i2").astype(np.float32) / 32768.0


def _next_pow2(n: int) -> int:
    size = 1
    while size < n:
        size *= 2
    return size


def _cross_correlation_scores(recording: np.ndarray, song: np.ndarray) -> np.ndarray:
    """録画（recording）の上で曲（song）をスライドしたときの内積の列（長さ len(recording)-len(song)+1）。

    録画が曲より短ければ、際立ちが低い結果になるだけで落ちないよう末尾を 0 で埋める。
    FFT（numpy.fft.rfft/irfft）で計算する。愚直なスライド（numpy.correlate の mode="valid"、
    O(len(recording)*len(song))）は、数分の音声のサンプル数（8kHz でも数百万）では
    現実的な時間で終わらないため。
    """
    if len(recording) < len(song):
        recording = np.pad(recording, (0, len(song) - len(recording)))
    m, n = len(recording), len(song)
    size = _next_pow2(m + n - 1)
    reversed_song = song[::-1]
    conv = np.fft.irfft(np.fft.rfft(recording, size) * np.fft.rfft(reversed_song, size), size)
    return conv[n - 1 : m]


@dataclass(frozen=True)
class Estimate:
    offset_s: float
    z: float


def estimate_offset(recording: np.ndarray, song: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Estimate:
    """録画（recording）の中で曲（song）が始まる時刻（秒）と、ピークの際立ち（z 値）。"""
    if len(song) == 0 or len(recording) == 0:
        return Estimate(0.0, 0.0)
    scores = _cross_correlation_scores(recording, song)
    peak = int(np.argmax(scores))
    mean, std = float(scores.mean()), float(scores.std())
    z = (float(scores[peak]) - mean) / std if std > 0 else 0.0
    return Estimate(peak / sample_rate, z)


def resolve_sync(project: Project, avatar: Avatar, raw: Path) -> SyncResult:
    """sync = "auto" なら相互相関で求め、数値ならそのまま手動オフセットとして使う。"""
    if not isinstance(avatar.sync, str):
        return SyncResult(float(avatar.sync), None)
    recording = _read_mono_pcm(raw)
    song = _read_mono_pcm(project.audio_path)
    estimate = estimate_offset(recording, song)
    return SyncResult(estimate.offset_s, estimate.z)


# --- クロマキー ------------------------------------------------------------------------------


def _rgb(key: str) -> tuple[int, int, int]:
    # "0xRRGGBB"。形式は config._check_key_color が検証済み
    value = key[2:]
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _despill_type(key: str) -> str:
    _, g, b = _rgb(key)
    return "green" if g > b else "blue"


def chroma_filter(avatar: Avatar) -> str:
    """colorkey・despill・アルファ付きフォーマットへの変換をつなげた filtergraph の断片。"""
    return (
        f"colorkey=color={avatar.key}:similarity={avatar.similarity}:blend={_COLORKEY_BLEND},"
        f"despill=type={_despill_type(avatar.key)}:mix={avatar.despill},"
        "format=yuva444p10le"
    )


# --- キャッシュ（キー抜き・頭出し済みの中間動画） --------------------------------------------


def _prepared_path(project: Project) -> Path:
    """内部実装のキャッシュ先。utavideo.toml からは見えないパス。"""
    return project.work_dir / _PREPARED_NAME


def _cache_path(project: Project) -> Path:
    return project.work_dir / _CACHE_NAME


def _stamp(path: Path) -> list[int | None]:
    """大きさと更新時刻（inputs.py・project.py と同じ考え方）。"""
    try:
        stat = path.stat()
    except OSError:
        return [None, None]
    return [stat.st_size, stat.st_mtime_ns]


def _digest(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    except OSError:
        return None


def _cache_key(avatar: Avatar, raw: Path, offset_s: float) -> dict[str, Any]:
    """答えが一つに決まる値（生の録画・key 系の設定・(自動なら)算出したオフセット・delay_ms）だけを持つ。

    scale・anchor・margin・layer（気分で変えたいもの）は含めない。変えても中間動画は作り直さない。
    """
    size, mtime_ns = _stamp(raw)
    return {
        "format": _CACHE_FORMAT,
        "raw": {"size": size, "mtime_ns": mtime_ns, "sha256": _digest(raw)},
        "key": avatar.key,
        "similarity": avatar.similarity,
        "despill": avatar.despill,
        "offset_s": offset_s,
        "delay_ms": avatar.delay_ms,
    }


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_fresh(project: Project, avatar: Avatar, raw: Path, offset_s: float) -> bool:
    """キャッシュ済みの中間動画をそのまま使えるか（存在し、キーが記録と一致するか）。"""
    if not _prepared_path(project).is_file():
        return False
    return _read_cache(_cache_path(project)) == _cache_key(avatar, raw, offset_s)


def _prepare_args(avatar: Avatar, raw: Path, start_s: float) -> list[str]:
    """出力ファイル名を除いた ffmpeg の引数。キー抜き・頭出し済みのアルファ付き動画を作る。

    音声は使わない（layers と同じ経路で重ねるだけの映像なので、project.audio_path が唯一の音声）。
    overlay モード（build/overlay.mov）と同じ ProRes 4444 / yuva444p10le で、アルファを保つ。
    """
    args = ["ffmpeg", *graph.QUIET]
    if start_s > 0:
        args += ["-ss", f"{start_s:.3f}"]
    args += [
        "-i", str(raw),
        "-an",
        "-vf", chroma_filter(avatar),
        "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
    ]  # fmt: skip
    return args


def prepare(project: Project, sync: SyncResult | None = None) -> tuple[Path, SyncResult]:
    """[avatar] を、graph.LayerSpec に渡せるキー抜き・頭出し済みの動画（絶対パス）にする。

    生の録画・key 系の設定・sync/delay_ms が前回と変わっていなければ、build/.work/ の中間動画を
    使い回す（変わっていれば ffmpeg でキー抜き・頭出しをやり直す）。呼び出し側は
    project.config.avatar が None でないことを保証すること。

    sync は、呼び出し側が analyze() 等で既に求めた結果があれば渡す（無ければここで求める）。
    音の頭出し（ffmpeg でのデコード＋FFT）は軽くないので、1回のコマンド実行で二重に計算しない
    ようにするため（issue #133）。
    """
    avatar = project.config.avatar
    assert avatar is not None
    raw = file_path(project.root, avatar)
    if sync is None:
        sync = resolve_sync(project, avatar, raw)
    start_s = max(0.0, sync.offset_s + avatar.delay_ms / 1000)
    output = _prepared_path(project)

    if not is_fresh(project, avatar, raw, sync.offset_s):
        err_console.print(
            "アバターを準備しています（キー抜き・頭出し。設定・録画が変わったときだけ、時間がかかります）…"
        )
        run(_prepare_args(avatar, raw, start_s), output, total_s=0)
        cache = json.dumps(_cache_key(avatar, raw, sync.offset_s), ensure_ascii=False, indent=2) + "\n"
        write_text(_cache_path(project), cache)
    return output.absolute(), sync


def layer_spec(project: Project, sync: SyncResult | None = None) -> graph.LayerSpec:
    """[avatar] を、常に表示する（区間指定なしの）graph.LayerSpec に変換する。

    scale・anchor・margin・layer（気分で変えたいもの）をそのまま渡し、[[layers]] と同じ
    合成コード（utavideo.graph の overlay）に乗せる。呼び出し側は project.config.avatar が
    None でないことを保証すること。sync は prepare() と同じ（呼び出し側の analyze() の結果を渡せる）。
    """
    avatar = project.config.avatar
    assert avatar is not None
    prepared, _ = prepare(project, sync)
    return graph.LayerSpec(
        file=prepared, scale=avatar.scale, anchor=avatar.anchor, margin=avatar.margin, layer=avatar.layer
    )


def all_layer_specs(project: Project, sync: SyncResult | None = None) -> tuple[graph.LayerSpec, ...]:
    """project.config.layers（[[layers]]）に、あれば [avatar] を1個のレイヤーとして足したもの。

    build・preview-bg・shorts・preview など、layer_specs を組み立てるすべての場所で共通して使う
    （cli.py・preview.py の間で同じ組み立てを重複させない）。sync は layer_spec() と同じ。
    """
    specs = tuple(layers.spec(project.root, layer) for layer in project.config.layers)
    if project.config.avatar is not None:
        specs += (layer_spec(project, sync),)
    return specs
