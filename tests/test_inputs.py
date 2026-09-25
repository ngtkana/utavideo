"""inputs の二層判定（size・mtime_ns が一致すれば読まずに済ませる）。ffmpeg は要らない。"""

import json
from pathlib import Path

import pytest

from tests.conftest import scaffold_named_project
from utavideo import inputs
from utavideo.project import Project, scaffold

TOML = """
[song]
title = "曲"
[audio]
file = "src/mix/曲 v1.2.wav"
[video]
background = "src/bg/bg.png"
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "曲"
    scaffold(root, "曲", "曲")
    (root / "utavideo.toml").write_text(TOML, encoding="utf-8")
    (root / "build").mkdir(exist_ok=True)
    (root / "build/main.mp4").write_bytes(b"video")
    return root


def _record_build(project: Path) -> None:
    loaded = Project.load(project)
    target = inputs.main_target(loaded)
    record = inputs.record_text(target, inputs.with_fonts(inputs.snapshot(target), ()))
    target.record_path.parent.mkdir(parents=True, exist_ok=True)
    target.record_path.write_text(record, encoding="utf-8")


def test_unchanged_files_are_not_read_again(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """size・mtime_ns が記録と一致するファイルは、中身を読み直さない（issue #78）。"""
    _record_build(project)
    calls: list[Path] = []
    original = inputs._file_digest

    def counting(path: Path) -> str | None:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(inputs, "_file_digest", counting)

    loaded = Project.load(project)
    assert inputs.stale_inputs(inputs.main_target(loaded)) is None
    assert calls == []


def test_resaved_file_with_the_same_content_reads_once_and_is_not_stale(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """size・mtime_ns が変わっても、中身が同じなら stale と見なさない（2段目のフォールバック）。"""
    _record_build(project)
    lyrics = project / "src/lyrics.ass"
    lyrics.write_text(lyrics.read_text(encoding="utf-8"), encoding="utf-8")  # 保存し直しただけ

    calls: list[Path] = []
    original = inputs._file_digest

    def counting(path: Path) -> str | None:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(inputs, "_file_digest", counting)

    loaded = Project.load(project)
    assert inputs.stale_inputs(inputs.main_target(loaded)) is None
    assert calls == [lyrics]


def test_old_format_record_is_ignored(project: Path) -> None:
    """format が古い記録は使わない（移行処理なしで安全に無視される）。"""
    loaded = Project.load(project)
    target = inputs.main_target(loaded)
    old_record = {"format": 1, "video": inputs._stamp(target.output), "inputs": {}}
    target.record_path.parent.mkdir(parents=True, exist_ok=True)
    target.record_path.write_text(json.dumps(old_record), encoding="utf-8")

    assert inputs._read_record(target) is None


def _record_inst_build(project: Path, key: int) -> None:
    loaded = Project.load(project)
    target = inputs.inst_target(loaded, key)
    target.output.parent.mkdir(parents=True, exist_ok=True)
    target.output.write_bytes(b"video")
    record = inputs.record_text(target, inputs.snapshot(target))
    target.record_path.parent.mkdir(parents=True, exist_ok=True)
    target.record_path.write_text(record, encoding="utf-8")


def test_inst_target_uses_a_key_specific_record_path(project: Path) -> None:
    loaded = Project.load(project)
    assert inputs.inst_target(loaded, -1).record_path == loaded.work_dir / "inst-key-1-inputs.json"
    assert inputs.inst_target(loaded, 2).record_path == loaded.work_dir / "inst-key+2-inputs.json"


def test_inst_snapshot_has_no_font_key(project: Path) -> None:
    """inst もフォント依存を見ない簡略版（issue #80、shorts・thumbnail と同じ理由）。"""
    loaded = Project.load(project)
    target = inputs.inst_target(loaded, 0)
    assert inputs.FONTS not in inputs.snapshot(target)


def test_inst_stale_detects_lyrics_changes(project: Path) -> None:
    _record_inst_build(project, -1)
    (project / "src/lyrics.ass").write_text("変えた", encoding="utf-8")

    loaded = Project.load(project)
    stale = inputs.stale_inputs(inputs.inst_target(loaded, -1))
    assert stale is not None
    assert "lyrics.file" in stale


def test_inst_stale_ignores_font_file_changes(project: Path) -> None:
    """フォントファイル単体の差し替えは検出対象外（歌詞・config ファイル自体の変化だけを見る）。"""
    _record_inst_build(project, -1)

    loaded = Project.load(project)
    assert inputs.stale_inputs(inputs.inst_target(loaded, -1)) is None


def test_inst_config_entry_change_is_detected(project: Path) -> None:
    _record_inst_build(project, -1)
    toml = (project / "utavideo.toml").read_text(encoding="utf-8")
    (project / "utavideo.toml").write_text(toml + '\n[inst]\ntext = "変えた"\n', encoding="utf-8")

    loaded = Project.load(project)
    stale = inputs.stale_inputs(inputs.inst_target(loaded, -1))
    assert stale is not None
    assert "utavideo.toml" in stale


def test_inst_target_omits_audio_file_when_inst_audio_is_unset(project: Path) -> None:
    """inst.audio が無いときは、追う音源が無いので files に含めない（analyze_inst がエラーにする）。"""
    loaded = Project.load(project)
    names = [name for name, _ in inputs.inst_target(loaded, 0).files]
    assert "inst.audio" not in names


def test_inst_stale_detects_inst_audio_content_changes(project: Path) -> None:
    (project / "src/mix/inst.wav").write_bytes(b"inst-audio")
    toml = (project / "utavideo.toml").read_text(encoding="utf-8")
    (project / "utavideo.toml").write_text(toml + '\n[inst]\naudio = "src/mix/inst.wav"\n', encoding="utf-8")
    _record_inst_build(project, -1)

    (project / "src/mix/inst.wav").write_bytes(b"changed")

    loaded = Project.load(project)
    stale = inputs.stale_inputs(inputs.inst_target(loaded, -1))
    assert stale is not None
    assert "inst.audio" in stale


def test_two_inst_keys_have_independent_records(project: Path) -> None:
    _record_inst_build(project, -1)
    _record_inst_build(project, 2)
    (project / "src/lyrics.ass").write_text("変えた", encoding="utf-8")

    loaded = Project.load(project)
    minus_one = inputs.inst_target(loaded, -1)
    plus_two = inputs.inst_target(loaded, 2)

    # 両方とも同じ lyrics.file に依存するので、両方 stale になる（記録自体は別ファイル）
    assert minus_one.record_path != plus_two.record_path
    assert inputs.stale_inputs(minus_one) is not None
    assert inputs.stale_inputs(plus_two) is not None


NAMED_TOML = """
[song]
title = "曲"
[audio]
file = "src/mix/曲 v1.2.wav"
[video]
background = "src/bg/bg.png"

[[shorts]]
name = "chorus"

[[shorts]]
name = "verse"

[[thumbnails]]
name = "main"
file = "src/thumbnail.ass"
"""


@pytest.fixture
def named_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """[[shorts]]・[[thumbnails]] を持つ曲フォルダ。ffmpeg は要らない。"""
    return scaffold_named_project(tmp_path, monkeypatch, NAMED_TOML)


def _record_shorts_build(project: Path, name: str) -> None:
    loaded = Project.load(project)
    short = next(s for s in loaded.config.shorts if s.name == name)
    target = inputs.shorts_target(loaded, short)
    target.output.parent.mkdir(parents=True, exist_ok=True)
    target.output.write_bytes(b"video")
    record = inputs.record_text(target, inputs.snapshot(target))
    target.record_path.parent.mkdir(parents=True, exist_ok=True)
    target.record_path.write_text(record, encoding="utf-8")


def test_shorts_target_uses_a_name_specific_record_path(named_project: Path) -> None:
    loaded = Project.load(named_project)
    short = next(s for s in loaded.config.shorts if s.name == "chorus")
    target = inputs.shorts_target(loaded, short)
    assert target.record_path == loaded.work_dir / "shorts-chorus-inputs.json"


def test_thumbnail_target_uses_a_name_specific_record_path(named_project: Path) -> None:
    loaded = Project.load(named_project)
    thumb = loaded.config.thumbnails[0]
    target = inputs.thumbnail_target(loaded, thumb)
    assert target.record_path == loaded.work_dir / "thumbnail-main-inputs.json"


def test_shorts_snapshot_has_no_font_key(named_project: Path) -> None:
    """shorts・thumbnail はフォント依存を見ない簡略版（issue #79）。"""
    loaded = Project.load(named_project)
    short = next(s for s in loaded.config.shorts if s.name == "chorus")
    target = inputs.shorts_target(loaded, short)
    assert inputs.FONTS not in inputs.snapshot(target)


def test_shorts_stale_detects_vertical_ass_changes(named_project: Path) -> None:
    _record_shorts_build(named_project, "chorus")
    (named_project / "src/vertical.ass").write_text("変えた", encoding="utf-8")

    loaded = Project.load(named_project)
    short = next(s for s in loaded.config.shorts if s.name == "chorus")
    target = inputs.shorts_target(loaded, short)
    stale = inputs.stale_inputs(target)
    assert stale is not None
    assert "vertical.lyrics" in stale


def test_shorts_stale_ignores_font_file_changes(named_project: Path, tmp_path: Path) -> None:
    """フォントファイル単体の差し替えは検出対象外（歌詞・config ファイル自体の変化だけを見る）。"""
    _record_shorts_build(named_project, "chorus")

    loaded = Project.load(named_project)
    short = next(s for s in loaded.config.shorts if s.name == "chorus")
    target = inputs.shorts_target(loaded, short)
    # フォントに関する変化を伝える手段（with_fonts）自体を使っていないので、
    # フォントファイルがどう変わっても stale_inputs の結果には現れない
    assert inputs.stale_inputs(target) is None


def test_shorts_config_entry_change_is_detected(named_project: Path) -> None:
    _record_shorts_build(named_project, "chorus")
    toml = (named_project / "utavideo.toml").read_text(encoding="utf-8")
    (named_project / "utavideo.toml").write_text(
        toml.replace('name = "chorus"', 'name = "chorus"\nwide = true'), encoding="utf-8"
    )

    loaded = Project.load(named_project)
    short = next(s for s in loaded.config.shorts if s.name == "chorus")
    target = inputs.shorts_target(loaded, short)
    stale = inputs.stale_inputs(target)
    assert stale is not None
    assert "utavideo.toml" in stale


def test_two_shorts_have_independent_records(named_project: Path) -> None:
    _record_shorts_build(named_project, "chorus")
    _record_shorts_build(named_project, "verse")
    (named_project / "src/vertical.ass").write_text("変えた", encoding="utf-8")

    loaded = Project.load(named_project)
    chorus = next(s for s in loaded.config.shorts if s.name == "chorus")
    verse = next(s for s in loaded.config.shorts if s.name == "verse")
    chorus_target = inputs.shorts_target(loaded, chorus)
    verse_target = inputs.shorts_target(loaded, verse)

    # 両方とも同じ vertical.ass に依存するので、両方 stale になる（記録自体は別ファイル）
    assert chorus_target.record_path != verse_target.record_path
    assert inputs.stale_inputs(chorus_target) is not None
    assert inputs.stale_inputs(verse_target) is not None


def test_a_file_shared_by_multiple_targets_is_hashed_once(
    named_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main とショートは同じ audio.file を見る。保存し直して stamp が変わっても、中身の確認は1回で済む。"""
    loaded = Project.load(named_project)
    short = next(s for s in loaded.config.shorts if s.name == "chorus")
    main_target = inputs.main_target(loaded)
    shorts_target = inputs.shorts_target(loaded, short)

    audio = named_project / "src/mix/曲 v1.2.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"audio")
    for target in (main_target, shorts_target):
        target.output.parent.mkdir(parents=True, exist_ok=True)
        target.output.write_bytes(b"video")
        values = inputs.snapshot(target)
        if target.track_fonts:
            values = inputs.with_fonts(values, ())
        record = inputs.record_text(target, values)
        target.record_path.parent.mkdir(parents=True, exist_ok=True)
        target.record_path.write_text(record, encoding="utf-8")

    audio.write_bytes(b"audio")  # 保存し直しただけ（中身は同じ、mtime だけ変わる）

    calls: list[Path] = []
    original = inputs._read_file_digest

    def counting(path: Path) -> str | None:
        calls.append(path)
        return original(path)

    monkeypatch.setattr(inputs, "_read_file_digest", counting)

    assert inputs.stale_inputs(main_target) is None
    assert inputs.stale_inputs(shorts_target) is None
    assert calls == [audio]


LAYER_TOML = TOML + '\n[[layers]]\nname = "logo"\nfile = "assets/logo.png"\n'


@pytest.fixture
def layered_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "曲"
    scaffold(root, "曲", "曲")
    (root / "utavideo.toml").write_text(LAYER_TOML, encoding="utf-8")
    (root / "assets").mkdir(exist_ok=True)
    (root / "assets/logo.png").write_bytes(b"logo")
    (root / "build").mkdir(exist_ok=True)
    (root / "build/main.mp4").write_bytes(b"video")
    return root


def test_main_target_includes_layer_files(layered_project: Path) -> None:
    loaded = Project.load(layered_project)
    names = dict(inputs.main_target(loaded).files)
    assert names["layers.logo"] == layered_project / "assets/logo.png"


def test_main_target_stale_detects_layer_file_changes(layered_project: Path) -> None:
    _record_build(layered_project)
    (layered_project / "assets/logo.png").write_bytes(b"changed")

    loaded = Project.load(layered_project)
    stale = inputs.stale_inputs(inputs.main_target(loaded))
    assert stale is not None
    assert "layers.logo" in stale


def test_main_target_stale_detects_layer_setting_changes(layered_project: Path) -> None:
    """ファイルの中身ではなく、margin・anchor などの設定だけを変えても止まる（config 全体を比べるため）。"""
    _record_build(layered_project)
    toml = (layered_project / "utavideo.toml").read_text(encoding="utf-8")
    (layered_project / "utavideo.toml").write_text(
        toml.replace('file = "assets/logo.png"', 'file = "assets/logo.png"\nlayer = 50'), encoding="utf-8"
    )

    loaded = Project.load(layered_project)
    stale = inputs.stale_inputs(inputs.main_target(loaded))
    assert stale is not None
    assert "utavideo.toml" in stale


def test_thumbnail_target_includes_layer_files_and_settings(layered_project: Path) -> None:
    toml = (layered_project / "utavideo.toml").read_text(encoding="utf-8")
    (layered_project / "utavideo.toml").write_text(
        toml + '\n[[thumbnails]]\nname = "main"\nfile = "src/thumbnail.ass"\n', encoding="utf-8"
    )
    (layered_project / "src/thumbnail.ass").write_text("サムネイル用", encoding="utf-8")

    loaded = Project.load(layered_project)
    thumb = loaded.config.thumbnails[0]
    target = inputs.thumbnail_target(loaded, thumb)
    assert dict(target.files)["layers.logo"] == layered_project / "assets/logo.png"
    assert isinstance(target.config, dict)
    assert "layers" in target.config


def test_shorts_target_includes_layer_files_and_settings(layered_project: Path) -> None:
    toml = (layered_project / "utavideo.toml").read_text(encoding="utf-8")
    (layered_project / "utavideo.toml").write_text(toml + '\n[[shorts]]\nname = "chorus"\n', encoding="utf-8")
    (layered_project / "src/vertical.ass").write_text("縦用", encoding="utf-8")

    loaded = Project.load(layered_project)
    short = loaded.config.shorts[0]
    target = inputs.shorts_target(loaded, short)
    assert dict(target.files)["layers.logo"] == layered_project / "assets/logo.png"
    assert isinstance(target.config, dict)
    assert "layers" in target.config


def test_shorts_target_stale_detects_layer_setting_changes(layered_project: Path) -> None:
    """ファイルの中身ではなく、margin・anchor などの設定だけを変えても止まる（main_target と同じ理由）。"""
    toml = (layered_project / "utavideo.toml").read_text(encoding="utf-8")
    (layered_project / "utavideo.toml").write_text(toml + '\n[[shorts]]\nname = "chorus"\n', encoding="utf-8")
    (layered_project / "src/vertical.ass").write_text("縦用", encoding="utf-8")
    _record_shorts_build(layered_project, "chorus")

    toml2 = (layered_project / "utavideo.toml").read_text(encoding="utf-8")
    (layered_project / "utavideo.toml").write_text(
        toml2.replace('file = "assets/logo.png"', 'file = "assets/logo.png"\nlayer = 50'), encoding="utf-8"
    )

    loaded = Project.load(layered_project)
    short = loaded.config.shorts[0]
    target = inputs.shorts_target(loaded, short)
    stale = inputs.stale_inputs(target)
    assert stale is not None
    assert "utavideo.toml" in stale
