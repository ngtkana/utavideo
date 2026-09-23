from pathlib import Path

import pytest

from utavideo import subs
from utavideo import thumbnail as thumbnail_module
from utavideo.config import ConfigError, Credit, Defaults, load_project_config
from utavideo.project import (
    SCAFFOLD_DIRS,
    Project,
    extract_version,
    find_project_root,
    next_revision,
    scaffold,
    to_windows_path,
)
from utavideo.schema import schema_path


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("曲名 v3.4", "v3.4"),
        ("Song v2.10", "v2.10"),
        ("曲名v0.1", "v0.1"),
        ("mix v1.0 v2.1", "v2.1"),
        ("audio", None),
        ("dev2.0", None),
        ("v1.0a", None),
        ("曲名 v3", None),  # vX.Y の2桁だけを読む
        ("曲名 v1.2.3", None),
        ("曲名 v1.02", None),  # 先頭に 0 が付くと v1.2 と別の音源として数えてしまう
        ("曲名 v01.2", None),
    ],
)
def test_extract_version(stem: str, expected: str | None) -> None:
    assert extract_version(stem) == expected


@pytest.mark.parametrize("slug", ["a/b", "Mr.", "CON", "con.mp4", "末尾の空白 ", "x" * 201, ""])
def test_scaffold_rejects_slugs_that_are_bad_file_names(tmp_path: Path, slug: str) -> None:
    with pytest.raises(ConfigError):
        scaffold(tmp_path / "x", "曲", slug)


def test_project_without_slug_makes_one_from_the_title(tmp_path: Path) -> None:
    root = tmp_path / "20260814 サンプル"
    scaffold(root, "サンプル", "sample")
    (root / "utavideo.toml").write_text(
        '[song]\ntitle = "A/B サンプル"\n[audio]\nfile = "src/mix/a v1.0.wav"\n'
        '[video]\nbackground = "src/bg/a.gif"\n',
        encoding="utf-8",
    )
    project = Project.load(root)
    assert project.slug == "A-B-サンプル"
    assert project.release_path("v1.0", 0) == root / "release" / "A-B-サンプル-v1.0.0.mp4"


def test_to_windows_path() -> None:
    path = Path("/mnt/d/Videos/20260913 新しい曲/build/preview/bg.mp4")
    assert to_windows_path(path) == r"D:\Videos\20260913 新しい曲\build\preview\bg.mp4"
    assert to_windows_path(Path("/home/user")) is None


def test_scaffold_creates_layout(tmp_path: Path) -> None:
    root = tmp_path / "20260915 新曲"
    result = scaffold(root, "新曲", "shin-kyoku")

    for rel in SCAFFOLD_DIRS:
        assert (root / rel).is_dir()
    assert result.skipped == []
    config = load_project_config(root / "utavideo.toml")
    assert config.song.title == "新曲"
    assert config.song.artist == ""
    assert config.song.slug == "shin-kyoku"
    assert config.audio.file == Path("src/mix/shin-kyoku-v1.0.wav")
    assert config.video.background == Path("src/bg/background.png")
    # 曲名は utavideo.toml にだけ書く（直すときに、どれが元なのかわからなくなるため）
    assert "新曲" not in (root / "src/lyrics.ass").read_text(encoding="utf-8")
    assert "新曲" not in (root / "README.md").read_text(encoding="utf-8")


def test_scaffold_writes_the_editor_schema_directive(tmp_path: Path) -> None:
    """taplo 対応のエディタが補完に使う #:schema が、TOML として読める形で1行目にある。"""
    root = tmp_path / "曲"
    scaffold(root, "曲", "x")
    first_line = (root / "utavideo.toml").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == f"#:schema {schema_path().as_uri()}"
    assert schema_path().is_file()


def test_scaffold_keeps_existing_files_and_detects_media(tmp_path: Path) -> None:
    root = tmp_path / "20260913 制作中の曲"
    (root / "src").mkdir(parents=True)
    (root / "for_studio").mkdir()
    (root / "src/audio.wav").write_bytes(b"wav")
    (root / "src/bg_loop.gif").write_bytes(b"gif")
    (root / "README.md").write_text("", encoding="utf-8")

    result = scaffold(root, "制作中の曲", "wip")

    assert root / "README.md" in result.skipped
    assert (root / "README.md").read_text(encoding="utf-8") == ""
    assert (root / "for_studio").is_dir()
    assert (root / "src/audio.wav").read_bytes() == b"wav"
    config = load_project_config(root / "utavideo.toml")
    assert config.audio.file == Path("src/audio.wav")
    assert config.video.background == Path("src/bg_loop.gif")

    again = scaffold(root, "制作中の曲", "wip")
    assert again.created == []


def test_scaffold_escapes_title_and_artist_in_toml(tmp_path: Path) -> None:
    root = tmp_path / "x"
    scaffold(root, 'say "hi" \\ ok', "x", artist="A & 'B'")
    song = load_project_config(root / "utavideo.toml").song
    assert song.title == 'say "hi" \\ ok'
    assert song.artist == "A & 'B'"


def test_project_paths_and_release_name(tmp_path: Path) -> None:
    root = tmp_path / "20260814 サンプル"
    scaffold(root, "サンプル", "sample")
    (root / "utavideo.toml").write_text(
        '[song]\ntitle = "サンプル"\nslug = "sample"\n[audio]\nfile = "src/mix/サンプル v3.4.wav"\n'
        '[video]\nbackground = "src/bg/a.gif"\n',
        encoding="utf-8",
    )
    project = Project.load(find_project_root(root / "src" / "mix"))
    assert project.root == root
    assert project.version == "v3.4"
    assert project.release_path("v3.4", 0) == root / "release" / "sample-v3.4.0.mp4"
    assert project.main_output == root / "build" / "main.mp4"


def test_next_revision_counts_released_videos(tmp_path: Path) -> None:
    root = tmp_path / "20260814 サンプル"
    scaffold(root, "サンプル", "sample")
    (root / "utavideo.toml").write_text(
        '[song]\ntitle = "サンプル"\n[audio]\nfile = "src/mix/サンプル v3.4.wav"\n'
        '[video]\nbackground = "src/bg/a.gif"\n',
        encoding="utf-8",
    )
    project = Project.load(root)
    assert next_revision(project.released("v3.4")) == 0

    for name in [
        "サンプル v3.4.mp4",  # 枝番を手で付けていた頃の1本目
        "サンプル v3.4.2.mp4",  # song.slug より前の名前
        "サンプル-v3.4.7.mp4",
        "サンプル v3.4.10.txt",  # 動画ではない
        "サンプル v3.4.01.mp4",  # utavideo が付けない形の番号
        "サンプル v3.5.4.mp4",  # 別の音源
        "ほかの曲 v3.4.5.mp4",
    ]:
        (root / "release" / name).write_bytes(b"")
    assert [revision for revision, _ in project.released("v3.4")] == [0, 2, 7]
    assert next_revision(project.released("v3.4")) == 8
    assert next_revision(project.released("v3.5")) == 5


def test_scaffold_copies_default_credits_and_hashtags(tmp_path: Path) -> None:
    credit = Credit(roles=("Vocal", "Mix"), name='歌う "人"', urls=("https://example.com/a",))
    defaults = Defaults(credits=(credit, credit), hashtags=("歌ってみた", "cover"))
    scaffold(tmp_path / "x", "曲", "song", defaults=defaults)
    config = load_project_config(tmp_path / "x" / "utavideo.toml")
    assert config.credits == defaults.credits
    assert config.description is not None
    assert config.description.hashtags == defaults.hashtags


def test_scaffold_creates_thumbnail_with_escaped_title(tmp_path: Path) -> None:
    root = tmp_path / "x"
    scaffold(root, "{曲}", "x", artist="A\\N")
    config = load_project_config(root / "utavideo.toml")
    (thumbnail,) = config.thumbnails
    assert (thumbnail.name, thumbnail.file) == ("main", Path("src/thumbnail.ass"))

    ass = subs.load(root / "src/thumbnail.ass")
    assert subs.play_res(ass) == config.video.size
    assert ass.info["YCbCr Matrix"] == "None"
    assert [e.text for e in subs.dialogues(ass)] == [r"\{曲\}", "A\\⁠N"]
    assert subs.lint_still(ass, size=config.video.size) == []


def test_init_with_existing_config_does_not_create_thumbnail(tmp_path: Path) -> None:
    root = tmp_path / "x"
    root.mkdir()
    (root / "utavideo.toml").write_text("# 自分の設定\n", encoding="utf-8")
    result = scaffold(root, "曲", "x")
    assert root / "utavideo.toml" in result.skipped
    assert not (root / "src/thumbnail.ass").exists()
    assert (root / "utavideo.toml").read_text(encoding="utf-8") == "# 自分の設定\n"


def test_thumbnail_paths_and_inherited_values(tmp_path: Path) -> None:
    root = tmp_path / "x"
    scaffold(root, "曲", "x")
    (root / "utavideo.toml").write_text(
        '[song]\ntitle = "曲"\n[audio]\nfile = "a.wav"\n[video]\nbackground = "bg.png"\nfocus = [0, 1]\n'
        '[[thumbnails]]\nname = "main"\nfile = "t.ass"\n'
        '[[thumbnails]]\nname = "square"\nfile = "s.ass"\nsize = [1080, 1080]\nfocus = [1, 0]\n',
        encoding="utf-8",
    )
    project = Project.load(root)
    main, square = project.config.thumbnails
    assert thumbnail_module.output_path(project.build_dir, main) == root / "build/thumbnail/main.png"
    assert thumbnail_module.bg_output_path(project.build_dir, main) == root / "build/thumbnail/bg/main.png"
    assert thumbnail_module.file_path(project.root, main) == root / "t.ass"
    video_size, video_focus = project.config.video.size, project.config.video.focus
    assert (
        thumbnail_module.size(main, video_size),
        thumbnail_module.focus(main, video_focus),
    ) == ((1920, 1080), (0.0, 1.0))
    assert (
        thumbnail_module.size(square, video_size),
        thumbnail_module.focus(square, video_focus),
    ) == ((1080, 1080), (1.0, 0.0))
