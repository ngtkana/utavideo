"""utavideo.avatar（頭出しの相互相関、クロマキーの filtergraph、キャッシュの鮮度、LayerSpec への変換）。

ffmpeg を実際に動かす部分（音声のデコード、実際のキー抜き・書き出し）は tests/test_render.py 側。
"""

import json
from pathlib import Path

import numpy as np
import pytest

from utavideo import avatar
from utavideo.config import Avatar
from utavideo.ffmpeg import AudioInfo
from utavideo.project import Project, scaffold

MINIMAL = """
[song]
title = "曲"
[audio]
file = "src/mix/曲 v1.0.wav"
[video]
background = "src/bg/bg.png"
"""


def _project_with_avatar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, avatar_toml: str) -> Project:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "曲"
    scaffold(root, "曲", "曲")
    (root / "utavideo.toml").write_text(MINIMAL + "[avatar]\n" + avatar_toml, encoding="utf-8")
    return Project.load(root)


# --- file_path（layers.file_path と同じ考え方） ----------------------------------------------


def test_file_path_is_relative_to_root() -> None:
    a = Avatar(file=Path("assets/avatar-raw.mp4"))
    assert avatar.file_path(Path("/song"), a) == Path("/song/assets/avatar-raw.mp4")


def test_file_path_keeps_an_absolute_path() -> None:
    a = Avatar(file=Path("/abs/avatar-raw.mp4"))
    assert avatar.file_path(Path("/song"), a) == Path("/abs/avatar-raw.mp4")


# --- 頭出し（相互相関・z 値） ------------------------------------------------------------------


def test_estimate_offset_recovers_a_known_offset() -> None:
    rng = np.random.default_rng(0)
    song = rng.normal(size=avatar.SAMPLE_RATE * 5).astype("float32")
    lead = np.zeros(avatar.SAMPLE_RATE * 2, dtype="float32")
    tail = np.zeros(avatar.SAMPLE_RATE * 1, dtype="float32")
    noise = rng.normal(scale=0.01, size=len(lead) + len(song) + len(tail)).astype("float32")
    recording = np.concatenate([lead, song, tail]) + noise

    estimate = avatar.estimate_offset(recording, song)

    assert estimate.offset_s == pytest.approx(2.0, abs=1 / avatar.SAMPLE_RATE)
    assert estimate.z > avatar.Z_WARNING_BELOW  # 白色雑音どうしの相関なのでピークが際立つ


def test_estimate_offset_pads_a_recording_shorter_than_the_song() -> None:
    """録画が曲より短くても落ちない（際立ちが低い結果になるだけ）。"""
    rng = np.random.default_rng(1)
    song = rng.normal(size=avatar.SAMPLE_RATE * 5).astype("float32")
    short_recording = song[: avatar.SAMPLE_RATE * 2]

    estimate = avatar.estimate_offset(short_recording, song)

    assert estimate.offset_s == 0.0


def test_estimate_offset_with_empty_signal_does_not_crash() -> None:
    empty = np.array([], dtype="float32")
    one = np.array([1.0], dtype="float32")
    assert avatar.estimate_offset(empty, one) == avatar.Estimate(0.0, 0.0)
    assert avatar.estimate_offset(one, empty) == avatar.Estimate(0.0, 0.0)


@pytest.mark.parametrize(
    ("z", "expected_level"),
    [(avatar.Z_ERROR_BELOW - 0.1, "error"), (avatar.Z_WARNING_BELOW - 0.1, "warning")],
)
def test_sync_issues_below_thresholds(z: float, expected_level: str) -> None:
    (issue,) = avatar.sync_issues(avatar.SyncResult(1.234, z))
    assert issue.level == expected_level


def test_sync_issues_above_warning_threshold_has_no_issues() -> None:
    assert avatar.sync_issues(avatar.SyncResult(1.234, avatar.Z_WARNING_BELOW + 1)) == []


def test_sync_issues_manual_offset_has_no_issues() -> None:
    """sync が数値（手動）のときは z が無いので、際立ちの警告・エラーは出ない。"""
    assert avatar.sync_issues(avatar.SyncResult(1.234, None)) == []


def test_analyze_reports_a_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project_with_avatar(tmp_path, monkeypatch, 'file = "src/avatar/avatar-raw.mp4"\n')
    result = avatar.analyze(project)
    assert result.sync is None
    assert any("ファイルがありません" in i.message for i in result.issues)


def test_analyze_reports_an_unsupported_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project_with_avatar(tmp_path, monkeypatch, 'file = "src/avatar/avatar-raw.txt"\n')
    (project.root / "src/avatar").mkdir(parents=True, exist_ok=True)
    (project.root / "src/avatar/avatar-raw.txt").write_text("not a video", encoding="utf-8")

    result = avatar.analyze(project)

    assert result.sync is None
    assert any("形式に対応していません" in i.message for i in result.issues)


def test_analyze_with_manual_sync_skips_reading_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sync が数値なら、録画の中身を読まない（ffmpeg を呼ばない）ので、壊れたファイルでも通る。"""
    project = _project_with_avatar(tmp_path, monkeypatch, 'file = "src/avatar/avatar-raw.mp4"\nsync = 3.25\n')
    raw = project.root / "src/avatar/avatar-raw.mp4"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"not a real video")

    result = avatar.analyze(project)

    assert result.issues == []
    assert result.sync == avatar.SyncResult(3.25, None)


def test_analyze_skips_sync_when_the_songs_audio_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """audio.file が無いときは頭出しをせず、落ちない（無いこと自体は analyze.audio_issues が報告する）。"""
    project = _project_with_avatar(tmp_path, monkeypatch, 'file = "src/avatar/avatar-raw.mp4"\n')
    raw = project.root / "src/avatar/avatar-raw.mp4"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"not a real video")
    assert not project.audio_path.is_file()  # MINIMAL の audio.file は実在しないダミーパス
    monkeypatch.setattr(avatar, "probe_audio", lambda path: AudioInfo(duration_s=1.0, has_sound=True))

    result = avatar.analyze(project)

    assert result.issues == []
    assert result.sync is None


def test_config_without_avatar_has_no_issues_and_no_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "曲"
    scaffold(root, "曲", "曲")
    (root / "utavideo.toml").write_text(MINIMAL, encoding="utf-8")
    project = Project.load(root)

    result = avatar.analyze(project)

    assert result.issues == []
    assert result.sync is None


# --- クロマキーの filtergraph ------------------------------------------------------------------


def test_chroma_filter_uses_blue_despill_for_the_default_key() -> None:
    filt = avatar.chroma_filter(Avatar(file=Path("x.mp4")))
    assert "colorkey=color=0x0000ff:similarity=0.3:blend=0.0" in filt
    assert "despill=type=blue:mix=0.2" in filt
    assert filt.endswith("format=yuva444p10le")


def test_chroma_filter_uses_green_despill_for_a_green_key() -> None:
    filt = avatar.chroma_filter(Avatar(file=Path("x.mp4"), key="0x00ff00"))
    assert "despill=type=green" in filt


def test_chroma_filter_reflects_similarity_and_despill() -> None:
    filt = avatar.chroma_filter(Avatar(file=Path("x.mp4"), similarity=0.5, despill=0.1))
    assert "similarity=0.5" in filt
    assert "mix=0.1" in filt


# --- キャッシュの鮮度判定 ----------------------------------------------------------------------


def test_cache_key_ignores_placement_fields(tmp_path: Path) -> None:
    """scale・anchor・margin・layer（気分で変えたいもの）はキーに含めない。"""
    raw = tmp_path / "avatar-raw.mp4"
    raw.write_bytes(b"raw-video")
    a1 = Avatar(file=raw, scale=1.0, anchor="center", margin=(0, 0), layer=0)
    a2 = Avatar(file=raw, scale=2.0, anchor="right", margin=(10, 10), layer=99)
    assert avatar._cache_key(a1, raw, 1.0) == avatar._cache_key(a2, raw, 1.0)


def test_cache_key_reflects_key_settings_and_offset(tmp_path: Path) -> None:
    raw = tmp_path / "avatar-raw.mp4"
    raw.write_bytes(b"raw-video")
    base = avatar._cache_key(Avatar(file=raw), raw, 1.0)
    assert base != avatar._cache_key(Avatar(file=raw, similarity=0.9), raw, 1.0)
    assert base != avatar._cache_key(Avatar(file=raw), raw, 2.0)
    assert base != avatar._cache_key(Avatar(file=raw, delay_ms=80), raw, 1.0)


def test_is_fresh_is_false_without_a_cache_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project_with_avatar(tmp_path, monkeypatch, 'file = "src/avatar/avatar-raw.mp4"\n')
    cfg = project.config.avatar
    assert cfg is not None
    raw = project.root / "src/avatar/avatar-raw.mp4"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"raw-video")
    avatar._prepared_path(project).parent.mkdir(parents=True, exist_ok=True)
    avatar._prepared_path(project).write_bytes(b"prepared")

    assert avatar.is_fresh(project, cfg, raw, 1.0) is False


def test_is_fresh_matches_a_recorded_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project_with_avatar(tmp_path, monkeypatch, 'file = "src/avatar/avatar-raw.mp4"\n')
    cfg = project.config.avatar
    assert cfg is not None
    raw = project.root / "src/avatar/avatar-raw.mp4"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"raw-video")
    avatar._prepared_path(project).parent.mkdir(parents=True, exist_ok=True)
    avatar._prepared_path(project).write_bytes(b"prepared")
    key = avatar._cache_key(cfg, raw, 1.0)
    avatar._cache_path(project).write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")

    assert avatar.is_fresh(project, cfg, raw, 1.0) is True

    raw.write_bytes(b"changed content")  # 生の録画が変われば古くなる
    assert avatar.is_fresh(project, cfg, raw, 1.0) is False


def test_prepare_reuses_a_given_sync_instead_of_recomputing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """呼び出し側が sync を渡せば、resolve_sync（ffmpeg でのデコード＋FFT）をやり直さない（issue #133）。

    analyze() が check・build 等の検査で既に求めた sync を、prepare() 系にそのまま渡すことで、
    1回のコマンド実行で頭出しの計算が二重に走らないようにする、という設計の要になる部分。
    """
    project = _project_with_avatar(tmp_path, monkeypatch, 'file = "src/avatar/avatar-raw.mp4"\n')
    monkeypatch.setattr(avatar, "is_fresh", lambda *a: True)  # ffmpeg でのキー抜きを避ける
    calls = 0

    def fake_resolve_sync(*args: object) -> avatar.SyncResult:
        nonlocal calls
        calls += 1
        return avatar.SyncResult(0.0, 20.0)

    monkeypatch.setattr(avatar, "resolve_sync", fake_resolve_sync)
    given = avatar.SyncResult(1.23, 15.0)

    _, sync = avatar.prepare(project, given)
    assert sync is given
    assert calls == 0  # 渡した sync をそのまま使い、計算し直さない

    avatar.prepare(project)  # sync を渡さなければ、従来通り自分で求める
    assert calls == 1


# --- LayerSpec への変換 -------------------------------------------------------------------------


def test_layer_spec_converts_the_placement_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project_with_avatar(
        tmp_path,
        monkeypatch,
        'file = "src/avatar/avatar-raw.mp4"\nscale = 1.5\nanchor = "right"\nmargin = [40, 0]\nlayer = 50\n',
    )
    prepared = Path("/build/.work/avatar-prepared.mov")
    monkeypatch.setattr(avatar, "prepare", lambda p, sync=None: (prepared, avatar.SyncResult(1.0, 20.0)))

    spec = avatar.layer_spec(project)

    assert spec.file == prepared
    assert (spec.scale, spec.anchor, spec.margin, spec.layer) == (1.5, "right", (40, 0), 50)
    assert (spec.start, spec.end) == (None, None)  # 区間指定なしの常時表示レイヤー
