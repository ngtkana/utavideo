"""utavideo sample が作る見本の曲フォルダ。素材を合成するので ffmpeg が要る。"""

import shutil
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont
from typer.testing import CliRunner

from tests.conftest import invoke
from utavideo import sample as sample_module
from utavideo import subs
from utavideo.analyze import analyze
from utavideo.cli import app
from utavideo.errors import UtavideoError
from utavideo.project import Project
from utavideo.schema import schema_path

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が必要")

runner = CliRunner()


@pytest.fixture
def sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # 見本が出す警告はユーザー設定（概要欄の書式）で変わるので、設定の無い状態にする
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    root = tmp_path / "sample"
    invoke("sample", str(root), "--small")
    monkeypatch.setenv("UTAVIDEO_FONT_DIRS", str(root / "src" / "fonts"))
    return root


def test_check_warns_only_about_the_lines_that_are_meant_to_warn(sample: Path) -> None:
    # 見本には、警告の出方を見せるための行がわざと入っている。増えたら見本か検査のどちらかが壊れている
    issues = analyze(Project.load(sample), "final").issues

    assert [issue.level for issue in issues] == ["warning", "warning"]
    assert r"2 行で \pos / \move を使っています" in issues[0].message
    assert "画面からはみ出しそうです" in issues[1].message
    assert "警告 2 件" in invoke("check", "-C", str(sample)).output


def test_the_warnings_do_not_change_with_the_user_config(
    sample: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 見本は手順書の判定にも使うので、概要欄の書式（人によって違う）で警告が増えてはいけない
    config = tmp_path / "other-config" / "utavideo"
    config.mkdir(parents=True)
    (config / "config.toml").write_text(
        '[description]\ntitle = "{title}（Cover: {singers}）"\nsinger_roles = ["歌唱"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config.parent))

    assert "警告 2 件" in invoke("check", "-C", str(sample)).output


def test_sample_writes_the_editor_schema_directive(sample: Path) -> None:
    first_line = (sample / "utavideo.toml").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == f"#:schema {schema_path().as_uri()}"


def test_the_bundled_font_has_a_glyph_for_the_song_name_overlay(sample: Path) -> None:
    # 字形の無い文字は別のフォントで描かれて環境ごとに絵が変わる（区切りの / を忘れやすい）
    config = Project.load(sample).config
    drawn = subs.format_overlay_text(config.overlay_text.text, config.song)
    cmap = TTFont(sample / sample_module.FONT_FILE).getBestCmap() or {}

    assert [ch for ch in drawn if ord(ch) not in cmap] == []


def test_the_bundled_font_is_a_static_regular_instance(sample: Path) -> None:
    # 可変フォントのまま同梱すると既定のウェイトが Regular と違うので、静的インスタンスであることを確かめる
    font = TTFont(sample / sample_module.FONT_FILE)

    assert "fvar" not in font
    assert font["name"].getDebugName(1) == sample_module.FONT_FAMILY
    assert font["OS/2"].usWeightClass == 400  # pyright: ignore[reportAttributeAccessIssue]
    assert (sample / sample_module.FONT_LICENSE_FILE).is_file()


def test_every_command_runs_on_the_sample(sample: Path) -> None:
    # overlay は 34 秒の ProRes 4444 で大きく遅いので、ここでは動かさない（手順でも既定では使わない）
    invoke("preview-bg", "-C", str(sample))
    invoke("build", "-C", str(sample))
    invoke("description", "-C", str(sample))
    invoke("release", "-C", str(sample))

    for rel in ("build/preview/bg.mp4", "build/main.mp4", "build/title.txt", "build/description.txt"):
        assert (sample / rel).is_file(), rel
    assert (sample / "release" / "sample-v1.0.0.mp4").is_file()


def test_sample_includes_a_working_avatar_with_correct_auto_sync(sample: Path) -> None:
    # [avatar] の見本は、音源を AVATAR_LEAD_S 秒遅らせて録画の音声に仕込んである（頭出しの正解値）
    config = Project.load(sample).config
    assert config.avatar is not None
    assert config.avatar.sync == "auto"
    output = invoke("check", "-C", str(sample)).output
    assert f"アバターの頭出し: {sample_module.AVATAR_LEAD_S:.3f} 秒" in output


def test_avatar_is_prepared_once_and_reused_on_the_next_build(sample: Path) -> None:
    first = invoke("build", "-C", str(sample)).output
    assert "アバターを準備しています" in first
    assert (sample / "build/.work/avatar-prepared.mov").is_file()
    assert (sample / "build/.work/avatar-cache.json").is_file()

    # 録画・設定が変わっていなければ、2 回目はキー抜きをやり直さない
    second = invoke("build", "-C", str(sample)).output
    assert "アバターを準備しています" not in second


def test_font_option_uses_an_installed_font_instead_of_synthesizing_one(tmp_path: Path) -> None:
    root = tmp_path / "sample"
    invoke("sample", str(root), "--small", "--font", "Some Installed Font")

    assert not (root / "src" / "fonts").exists()
    assert "Some Installed Font" in (root / "src" / "lyrics.ass").read_text(encoding="utf-8")


def test_sample_does_not_touch_an_existing_folder(tmp_path: Path) -> None:
    root = tmp_path / "sample"
    root.mkdir()
    result = runner.invoke(app, ["sample", str(root)])

    assert result.exit_code == 1
    assert list(root.iterdir()) == []


def test_sample_removes_the_half_made_folder_when_it_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 素材の合成で失敗しても、同じパスでやり直せる（残っていると「既にあります」で止まる）
    def boom(*args: object, **kwargs: object) -> list[Path]:
        raise UtavideoError("素材の合成に失敗しました")

    monkeypatch.setattr(sample_module, "_materials", boom)
    root = tmp_path / "sample"
    result = runner.invoke(app, ["sample", str(root), "--small"])

    assert result.exit_code == 1
    assert not root.exists()
