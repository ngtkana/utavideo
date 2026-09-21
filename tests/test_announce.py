import tomllib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from utavideo import announce
from utavideo.announce import classify, hashtag_error, weight
from utavideo.cli import app
from utavideo.config import AnnounceFormat, DescriptionFormat, ProjectConfig, UserConfig, load_project_config

runner = CliRunner()

YOUTUBE = "https://youtu.be/abcdefghijk"
NICONICO = "https://www.nicovideo.jp/watch/sm12345678"

SONG: dict[str, Any] = {
    "song": {"title": "曲", "artist": "作者"},
    "audio": {"file": "src/mix/曲 v1.0.wav"},
    "video": {"background": "src/bg/bg.png"},
    "credits": [{"roles": ["Vocal"], "name": "歌う人"}],
    "uploads": [{"url": NICONICO}, {"url": YOUTUBE}],
    "announce": {"text": "\n歌いました！\n\n", "hashtags": ["歌ってみた", "cover"]},
}


def _config(**overrides: Any) -> ProjectConfig:
    return ProjectConfig.model_validate({**SONG, **overrides})


def _render(config: ProjectConfig, fmt: AnnounceFormat | None = None) -> str:
    return announce.render(config, fmt or AnnounceFormat(), DescriptionFormat())


def _lint(config: ProjectConfig, fmt: AnnounceFormat | None = None, *, warn: bool = True) -> list[Any]:
    issues = announce.lint(config, fmt or AnnounceFormat(), DescriptionFormat(), warn_no_uploads=warn)
    return [(issue.level, issue.message) for issue in issues]


def test_render_default_format_lists_links_in_the_order_of_sites() -> None:
    assert _render(_config()) == (
        "【動画投稿】\n"
        "歌いました！\n"
        "\n"
        "『曲 / 作者』\n"
        "\n"
        f"YouTube » {YOUTUBE}\n"
        f"ニコニコ動画 » {NICONICO}\n"
        "\n"
        "#歌ってみた #cover\n"
    )


def test_render_follows_order_and_sites() -> None:
    fmt = AnnounceFormat(
        header="",
        work="{title}（{singers}）",
        link="{site}: {url}",
        sites={"niconico": "N", "youtube": "Y"},
        order=("work", "links", "hashtags", "", "text"),
    )
    assert _render(_config(), fmt) == (
        f"曲（歌う人）\nN: {NICONICO}\nY: {YOUTUBE}\n#歌ってみた #cover\n\n歌いました！\n"
    )


def test_render_skips_empty_blocks_and_collapses_blank_lines() -> None:
    config = _config(uploads=[], announce=None)
    assert _render(config) == "【動画投稿】\n\n『曲 / 作者』\n"
    fmt = AnnounceFormat(order=("", "text", "", "", "links", "", "work", "", ""))
    assert _render(config, fmt) == "『曲 / 作者』\n"


def test_header_is_not_formatted() -> None:
    fmt = AnnounceFormat(header="{title}", order=("header",))
    assert _render(_config(), fmt) == "{title}\n"


def test_order_allows_repeated_blank_lines_but_not_blocks() -> None:
    AnnounceFormat.model_validate({"order": ["", "work", "", ""]})
    with pytest.raises(ValidationError, match="2回"):
        AnnounceFormat.model_validate({"order": ["work", "", "work"]})
    with pytest.raises(ValidationError):
        AnnounceFormat.model_validate({"order": ["title"]})


def test_sites_accepts_only_known_keys_and_keeps_the_written_order() -> None:
    data = tomllib.loads('[announce]\nsites = { niconico = "N", youtube = "Y" }\n')
    fmt = UserConfig.model_validate(data).announce
    assert list(fmt.sites) == ["niconico", "youtube"]
    with pytest.raises(ValidationError):
        AnnounceFormat.model_validate({"sites": {"bilibili": "B"}})


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://youtu.be/abcdefghijk", "youtube"),
        ("https://youtu.be/abcdefghijk?si=share", "youtube"),
        ("https://www.youtube.com/watch?v=A-_0123456z", "youtube"),
        ("https://youtube.com/watch?v=abcdefghijk&si=x", "youtube"),
        ("https://m.youtube.com/watch?v=abcdefghijk", "youtube"),
        ("https://www.nicovideo.jp/watch/sm12345678", "niconico"),
        ("https://sp.nicovideo.jp/watch/so123?ref=share", "niconico"),
        ("https://nicovideo.jp/watch/nm1", "niconico"),
        ("https://nico.ms/sm12345678", "niconico"),
    ],
)
def test_classify_accepts_video_urls(url: str, site: str) -> None:
    upload = classify(url)
    assert (upload.site, upload.issues) == (site, ())


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://youtu.be/abcdefghijk", "https://"),
        ("youtu.be/abcdefghijk", "https://"),
        ("https://www.youtube.com/shorts/abcdefghijk", "対象外"),
        ("https://www.youtube.com/live/abcdefghijk", "対応していない形"),
        ("https://www.youtube.com/@channel", "対応していない形"),
        ("https://youtu.be/abcdefghij", "動画 ID"),
        ("https://youtu.be/abcdefghijkl", "動画 ID"),
        ("https://youtu.be/abcdefghij!", "動画 ID"),
        ("https://youtu.be/", "動画 ID"),
        ("https://youtu.be/abcdefghijk/x", "動画 ID"),
        ("https://www.youtube.com/watch?v=abcdefghijk&v=bcdefghijkl", "対応していない形"),
        ("https://youtube.com.example/watch?v=abcdefghijk", "判定できません"),
        ("https://notyoutube.com/watch?v=abcdefghijk", "判定できません"),
        ("https://youtube.com:8080/watch?v=abcdefghijk", "対応していない形"),
        ("https://www.nicovideo.jp/watch/lv123", "動画 ID"),
        ("https://www.nicovideo.jp/watch/sm", "動画 ID"),
        ("https://www.nicovideo.jp/user/1", "対応していない形"),
        ("https://nico.ms/sm1/x", "対応していない形"),
        ("https://example.com/watch?v=abcdefghijk", "判定できません"),
    ],
)
def test_classify_rejects_other_urls(url: str, message: str) -> None:
    upload = classify(url)
    assert upload.site is None
    [issue] = upload.issues
    assert issue.level == "error"
    assert message in issue.message
    assert url in issue.message


@pytest.mark.parametrize(
    ("url", "site"),
    [
        ("https://www.youtube.com/watch?v=abcdefghijk&t=30", "youtube"),
        ("https://www.youtube.com/watch?v=abcdefghijk&list=PL123", "youtube"),
        ("https://www.youtube.com/watch?v=abcdefghijk&t=30&list=PL123", "youtube"),
        ("https://www.youtube.com/watch?v=abcdefghijk#t=30", "youtube"),
        ("https://youtu.be/abcdefghijk?t=30", "youtube"),
        ("https://www.nicovideo.jp/watch/sm9?from=90", "niconico"),
        ("https://nico.ms/sm9?from=90", "niconico"),
    ],
)
def test_classify_warns_links_that_do_not_start_at_the_beginning(url: str, site: str) -> None:
    upload = classify(url)
    assert upload.site == site
    [issue] = upload.issues
    assert issue.level == "warning"
    assert "頭から再生されません" in issue.message


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("abc\n", 3),  # 末尾の改行は数えない
        ("a\nb", 3),
        ("\u10ff", 1),
        ("\u1100", 2),
        ("\u1fff", 2),
        ("\u2000", 1),
        ("\u200d", 1),
        ("\u200e", 2),
        ("\u200f", 2),
        ("\u2010", 1),
        ("\u201f", 1),
        ("\u2020", 2),
        ("\u2031", 2),
        ("\u2032", 1),
        ("\u2037", 1),
        ("\u2038", 2),
        ("»", 1),
        ("【】『』・…", 12),
        ("\u3000", 2),
        ("あ", 2),
        ("\U0001f31f", 2),
        ("\u304b\u3099", 2),  # NFC で「が」1文字になる
        ("https://youtu.be/abcdefghijk", 23),
        ("http://example.com/a/very/long/path/that/is/longer/than/twenty-three", 23),
        ("example.com", 23),
        # スキームの無いものは TLD が一覧にあるときだけ URL（twitter-text 3.1.0 で確かめた値）
        ("nicovideo.jp", 23),
        ("www.nicovideo.jp", 23),
        ("nico.ms/sm9", 23),
        ("Example.COM", 23),
        ("example.みんな", 23),
        ("『Mr.Children』", 15),
        ("feat.Ado", 8),
        ("St.Vincent", 10),
        ("utavideo.toml", 13),
        ("example.com+1", 13),
        ("_example.com", 12),
        ("＠example.com", 2 + 23),
        ("foo.com.xyzq", 23 + 5),
        ("見て example.com。", 2 + 2 + 1 + 23 + 2),
        ("告知 https://x.com/a。", 2 + 2 + 1 + 23 + 2),
        ("見て https://x.com/a.", 2 + 2 + 1 + 23 + 1),
        ("v1.0", 4),
        ("#歌ってみた", 11),
    ],
)
def test_weight_follows_twitter_text_v3(text: str, expected: int) -> None:
    assert weight(text) == expected


def test_weight_of_the_default_announcement() -> None:
    text = _render(_config())
    lines = [
        6 * 2,  # 【動画投稿】
        6 * 2,  # 歌いました！
        0,
        5 * 2 + 3,  # 『曲 / 作者』
        0,
        len("YouTube » ") + 23,
        6 * 2 + len(" » ") + 23,
        0,
        1 + 5 * 2 + len(" #cover"),  # #歌ってみた #cover
    ]
    expected = sum(lines) + len(lines) - 1  # 行の間の改行。末尾の改行は数えない
    assert weight(text) == expected


@pytest.mark.parametrize(
    "tag",
    ["歌ってみた", "cover", "vsinger_2026", "ボカロ〜", "Ｖ・シンガー", "歌コレ2024秋", "が゛"],
)
def test_hashtags_that_x_links_as_a_whole(tag: str) -> None:
    assert hashtag_error(tag) is None


@pytest.mark.parametrize(
    ("tag", "message"),
    [
        ("歌ってみた-cover", "'-'"),
        ("v1.0", "'.'"),
        ("やった!", "'!'"),
        ("R&B", "'&'"),
        ("rock'n'roll", '"\'"'),
        ("歌♪", "'♪'"),
        ("2026", "数字"),
        ("_", "数字"),
    ],
)
def test_hashtags_that_x_cuts(tag: str, message: str) -> None:
    reason = hashtag_error(tag)
    assert reason is not None
    assert message in reason


def test_lint_passes_a_complete_announcement() -> None:
    assert _lint(_config()) == []


def test_lint_warns_missing_uploads_only_when_asked() -> None:
    config = _config(uploads=[])
    assert _lint(config, warn=False) == []
    [(level, message)] = _lint(config)
    assert level == "warning"
    assert "リンクがありません" in message


def test_lint_reports_duplicate_sites_and_sites_missing_from_the_format() -> None:
    config = _config(uploads=[{"url": YOUTUBE}, {"url": "https://www.youtube.com/watch?v=bcdefghijkl"}])
    [(level, message)] = _lint(config)
    assert level == "error"
    assert "2 つ" in message

    [(level, message)] = _lint(_config(), AnnounceFormat(sites={"youtube": "YouTube"}))
    assert level == "error"
    assert 'sites = { youtube = "YouTube", niconico = "ニコニコ動画" }' in message


def test_lint_reports_hashtags_singers_length_and_broken_formats() -> None:
    config = _config(credits=[], announce={"text": "あ" * 140, "hashtags": ["歌ってみた-cover"]})
    fmt = AnnounceFormat(work="{title}（{singers}）")
    levels = [level for level, _ in _lint(config, fmt)]
    messages = "\n".join(message for _, message in _lint(config, fmt))
    assert levels == ["error", "warning", "warning"]
    assert "歌ってみた-cover" in messages
    assert "{singers}" in messages
    assert "を超えています" in messages

    assert _lint(_config(), AnnounceFormat(max_weight=10_000)) == []
    [(level, message)] = _lint(_config(uploads=[]), AnnounceFormat(link="{site} {ur}"), warn=False)
    assert (level, "announce.link" in message) == ("error", True)
    [(level, message)] = _lint(_config(), AnnounceFormat(work="{composer}"))
    assert (level, "announce.work" in message) == ("error", True)


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    user_config = tmp_path / "config/utavideo/config.toml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text('[defaults]\nannounce_hashtags = ["歌ってみた"]\n', encoding="utf-8")
    root = tmp_path / "20260917-song"
    created = runner.invoke(app, ["new", str(root), "--title", "曲", "--artist", "作者"])
    assert created.exit_code == 0, created.output
    return root


def test_announce_command_writes_a_draft_and_then_the_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _setup(tmp_path, monkeypatch)
    config = load_project_config(root / "utavideo.toml")
    assert config.announce is not None
    assert config.announce.hashtags == ("歌ってみた",)

    result = runner.invoke(app, ["announce", "-C", str(root)])
    assert result.exit_code == 0, result.output
    assert "リンクがありません" in result.output
    output = root / "build/announce.txt"
    assert output.read_text(encoding="utf-8") == "【動画投稿】\n\n『曲 / 作者』\n\n#歌ってみた\n"

    with (root / "utavideo.toml").open("a", encoding="utf-8") as f:
        f.write(f'\n[[uploads]]\nurl = "{YOUTUBE}"\n')
    result = runner.invoke(app, ["announce", "-C", str(root)])
    assert result.exit_code == 0, result.output
    assert f"YouTube » {YOUTUBE}\n" in output.read_text(encoding="utf-8")
    assert "長さ:" in result.output


def test_announce_command_does_not_write_when_a_url_is_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _setup(tmp_path, monkeypatch)
    with (root / "utavideo.toml").open("a", encoding="utf-8") as f:
        f.write('\n[[uploads]]\nurl = "https://www.youtube.com/shorts/abcdefghijk"\n')
    result = runner.invoke(app, ["announce", "-C", str(root)])
    assert result.exit_code == 1
    assert "対象外" in result.output
    assert not (root / "build/announce.txt").exists()
