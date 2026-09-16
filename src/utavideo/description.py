"""utavideo.toml のクレジット・素材から、動画投稿サイトの概要欄とタイトルを作る。"""

from pathlib import Path

from utavideo.config import ConfigError, Description, DescriptionFormat, ProjectConfig, format_setting
from utavideo.project import Project
from utavideo.subs import Issue

# YouTube Data API の上限（docs/verification/20260916-description.md）
TITLE_MAX_CHARS = 100
BODY_MAX_BYTES = 5000


def singers(config: ProjectConfig, fmt: DescriptionFormat) -> list[str]:
    return [credit.name for credit in config.credits if set(credit.roles) & set(fmt.singer_roles)]


def song_fields(config: ProjectConfig, fmt: DescriptionFormat) -> dict[str, str]:
    """タイトルと告知文の書式で使える {title}・{artist}・{label}・{singers} の値。"""
    song = config.song
    return {
        "title": song.title,
        "artist": song.artist,
        "label": song.label,
        "singers": fmt.singer_separator.join(singers(config, fmt)),
    }


def no_singers_issue(
    config: ProjectConfig, fmt: DescriptionFormat, template: str, where: str
) -> Issue | None:
    """書式が {singers} を使うのに、入る人がいないときの警告。"""
    if "{singers}" not in template or singers(config, fmt):
        return None
    roles = ", ".join(fmt.singer_roles)
    return Issue(
        "warning", f"{where}の {{singers}} に入る人がいません（roles に {roles} を持つ credits が無い）"
    )


def render_title(config: ProjectConfig, fmt: DescriptionFormat) -> str:
    if config.description is not None and config.description.title is not None:
        return config.description.title
    return format_setting(fmt.title, "ユーザー設定の description.title", **song_fields(config, fmt))


def render_body(config: ProjectConfig, fmt: DescriptionFormat) -> str:
    """概要欄。中身の無いブロックは出さない。"""
    description = config.description or Description()
    chunks: list[tuple[str, str]] = []  # (text / section / hashtags, 文字列)

    def add_section(name: str, lines: list[str]) -> None:
        heading = format_setting(fmt.heading, "ユーザー設定の description.heading", section=name)
        chunks.append(("section", "\n".join([heading, *lines])))

    for block in fmt.order:
        match block:
            case "text":
                if text := description.text.strip():
                    chunks.append(("text", text))
            case "original":
                if config.song.original_urls:
                    add_section(fmt.original_heading, list(config.song.original_urls))
            case "credits":
                people: dict[tuple[str, ...], list[str]] = {}
                for credit in config.credits:
                    line = fmt.name_url_separator.join([credit.name, *credit.urls])
                    people.setdefault(credit.roles, []).append(line)
                for roles, lines in people.items():
                    add_section(fmt.role_separator.join(roles), lines)
            case "materials":
                urls: dict[str, list[str]] = {}
                for material in config.materials:
                    if material.urls:
                        urls.setdefault(material.section, []).extend(material.urls)
                for name, lines in urls.items():
                    add_section(name, lines)
            case "hashtags":
                if description.hashtags:
                    chunks.append(("hashtags", " ".join(f"#{tag}" for tag in description.hashtags)))

    body = ""
    for i, (kind, content) in enumerate(chunks):
        if i:
            if kind == "hashtags":
                gap = fmt.hashtags_gap
            elif kind == chunks[i - 1][0] == "section":
                gap = fmt.section_gap
            else:
                gap = 1
            body += "\n" * (gap + 1)
        body += content
    return body + "\n" if body else ""


def lint(project: Project, fmt: DescriptionFormat) -> list[Issue]:
    config = project.config
    try:
        title = render_title(config, fmt)
        body = render_body(config, fmt)
    except ConfigError as e:
        return [Issue("error", str(e))]

    issues: list[Issue] = []
    credited: set[Path] = set()
    for material in config.materials:
        for file in material.files:
            path = project.resolve(file)
            if path.exists():
                credited.add(path.resolve())
            else:
                issues.append(Issue("warning", f"materials.files のファイルがありません: {path}"))
    background = project.background_path
    if background.is_file() and background.resolve() not in credited:
        issues.append(
            Issue(
                "warning",
                "video.background がどの materials.files にもありません"
                f"（クレジットの書き忘れ）: {background}",
            )
        )

    uses_auto_title = config.description is None or config.description.title is None
    if uses_auto_title and (issue := no_singers_issue(config, fmt, fmt.title, "タイトル")):
        issues.append(issue)
    if len(title) > TITLE_MAX_CHARS:
        issues.append(
            Issue(
                "warning",
                f"タイトルが {len(title)} 文字で、YouTube の上限 {TITLE_MAX_CHARS} 文字を超えています",
            )
        )
    if (size := len(body.encode())) > BODY_MAX_BYTES:
        issues.append(
            Issue(
                "warning", f"概要欄が {size} バイトで、YouTube の上限 {BODY_MAX_BYTES} バイトを超えています"
            )
        )
    if any(ch in title + body for ch in "<>"):
        issues.append(Issue("warning", "タイトルか概要欄に < または > があります（YouTube では使えません）"))
    return issues
