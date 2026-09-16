"""投稿した動画の URL と曲の情報から、SNS（X）の告知文を作る。"""

import json
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from utavideo.config import (
    Announce,
    AnnounceFormat,
    ConfigError,
    DescriptionFormat,
    ProjectConfig,
    Site,
    format_setting,
)
from utavideo.description import singers
from utavideo.subs import Issue

SITE_NAMES: dict[Site, str] = {"youtube": "YouTube", "niconico": "ニコニコ動画"}

# twitter-text の config/v3.json（docs/verification/20260917-announce.md）
DEFAULT_WEIGHT = 2
LIGHT_RANGES = ((0x0000, 0x10FF), (0x2000, 0x200D), (0x2010, 0x201F), (0x2032, 0x2037))
URL_WEIGHT = 23

_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_NICONICO_ID = re.compile(r"(?:sm|so|nm)[0-9]+")

# 長さの概算に使う URL の簡易な判定。スキームの無い「example.com」も X は URL として数える。
# 末尾の句読点は URL に含めない（twitter-text も含めない）
_URL = re.compile(
    r"(?:https?://[!-~]+|(?<![A-Za-z0-9@$#.\-_/])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[!-~]*)?)",
    re.IGNORECASE,
)
_URL_TRAILING = ".,:;!?'\"()[]"

# twitter-text の hashtagSpecialChars。文字・結合文字・数字のほかに、ハッシュタグに使える記号
_HASHTAG_SPECIAL = frozenset(
    "_\u200c\u200d\ua67e\u05be\u05f3\u05f4\uff5e\u301c\u309b\u309c\u30a0\u30fb\u3003\u0f0b\u0f0c\u00b7"
)


@dataclass(frozen=True)
class Upload:
    url: str
    site: Site | None
    issues: tuple[Issue, ...]


def classify(url: str) -> Upload:
    """URL のサイトを判定し、動画の URL の形かを調べる。"""

    def error(message: str) -> Upload:
        return Upload(url, None, (Issue("error", f"uploads.url: {message}: {url}"),))

    if not url.startswith("https://"):
        return error("https:// から始まる形で書いてください")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        has_extra = parts.port is not None or parts.username is not None
    except ValueError:
        return error("URL の形が不正です")

    def on(domain: str) -> bool:
        # 部分一致にすると youtube.com.example まで通るので、完全一致かサブドメインだけ
        return host == domain or host.endswith(f".{domain}")

    youtube_forms = "https://www.youtube.com/watch?v=ID・https://youtu.be/ID"
    niconico_forms = "https://www.nicovideo.jp/watch/ID・https://nico.ms/ID"
    if on("youtube.com") or host == "youtu.be":
        if parts.path.startswith("/shorts/"):
            return error("ショート動画（/shorts/）の告知は、今は対象外です")
        if has_extra:
            return error(f"対応していない形です（受け付ける形: {youtube_forms}）")
        query = parse_qs(parts.query)
        if host == "youtu.be":
            video_id = parts.path.removeprefix("/") if parts.path.count("/") == 1 else None
        elif parts.path == "/watch" and len(query.get("v", [])) == 1:
            video_id = query["v"][0]
        else:
            return error(f"対応していない形です（受け付ける形: {youtube_forms}）")
        if video_id is None or not _YOUTUBE_ID.fullmatch(video_id):
            return error("YouTube の動画 ID が不正です（英数字・_・- の 11 文字）")
        issues: list[Issue] = []
        if extra := [name for name in ("t", "list") if name in query]:
            names = "・".join(extra)
            message = f"uploads.url に {names} が付いています（動画の頭から再生されません）: {url}"
            issues.append(Issue("warning", message))
        return Upload(url, "youtube", tuple(issues))
    if on("nicovideo.jp") or host == "nico.ms":
        if has_extra:
            return error(f"対応していない形です（受け付ける形: {niconico_forms}）")
        prefix = "/" if host == "nico.ms" else "/watch/"
        video_id = parts.path.removeprefix(prefix)
        if not parts.path.startswith(prefix) or "/" in video_id:
            return error(f"対応していない形です（受け付ける形: {niconico_forms}）")
        if not _NICONICO_ID.fullmatch(video_id):
            return error("ニコニコ動画の動画 ID が不正です（sm・so・nm と数字）")
        return Upload(url, "niconico", ())
    return error(f"サイトを判定できません（対応しているのは {youtube_forms}・{niconico_forms}）")


def render(config: ProjectConfig, fmt: AnnounceFormat, description_fmt: DescriptionFormat) -> str:
    """告知文。中身の無いブロックは出さず、空行は続けず、先頭と末尾にも置かない。"""
    announce = config.announce or Announce()
    uploads = [classify(upload.url) for upload in config.uploads]
    lines: list[str] = []
    for block in fmt.order:
        match block:
            case "":
                lines.append("")
            case "header":
                if fmt.header:
                    lines.append(fmt.header)
            case "text":
                if text := announce.text.strip():
                    lines.append(text)
            case "work":
                song = config.song
                work = format_setting(
                    fmt.work,
                    "ユーザー設定の announce.work",
                    title=song.title,
                    artist=song.artist,
                    label=song.label,
                    singers=description_fmt.singer_separator.join(singers(config, description_fmt)),
                )
                if work:
                    lines.append(work)
            case "links":
                for site, name in fmt.sites.items():
                    for upload in uploads:
                        if upload.site == site:
                            line = format_setting(
                                fmt.link, "ユーザー設定の announce.link", site=name, url=upload.url
                            )
                            lines.append(line)
            case "hashtags":
                if announce.hashtags:
                    lines.append(" ".join(f"#{tag}" for tag in announce.hashtags))

    text = ""
    for line in lines:
        if line == "" and (text == "" or text.endswith("\n\n")):
            continue
        text += line + "\n"
    text = text.rstrip("\n")
    return text + "\n" if text else ""


def weight(text: str) -> int:
    """X の数え方での長さ（twitter-text v3）。絵文字の組み合わせは部品ごとに数えるので多めになる。"""
    text = unicodedata.normalize("NFC", text).removesuffix("\n")
    total = 0
    position = 0
    for start, end in _urls(text):
        total += _chars_weight(text[position:start]) + URL_WEIGHT
        position = end
    return total + _chars_weight(text[position:])


def _urls(text: str) -> Iterator[tuple[int, int]]:
    for match in _URL.finditer(text):
        url = match.group().rstrip(_URL_TRAILING)
        yield match.start(), match.start() + len(url)


def _chars_weight(text: str) -> int:
    return sum(1 if any(lo <= ord(ch) <= hi for lo, hi in LIGHT_RANGES) else DEFAULT_WEIGHT for ch in text)


def hashtag_error(tag: str) -> str | None:
    """X でハッシュタグとしてそのまま使えない理由。使えるなら None。"""
    bad = sorted({ch for ch in tag if not _hashtag_char(ch)}, key=tag.index)
    if bad:
        chars = "".join(bad)
        return f"X ではタグが途中で切れる文字 {chars!r} があります"
    if not any(unicodedata.category(ch)[0] in "LM" for ch in tag):
        return "数字や記号だけのタグは X ではタグになりません"
    return None


def _hashtag_char(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LM" or unicodedata.category(ch) == "Nd" or ch in _HASHTAG_SPECIAL


def lint(
    config: ProjectConfig,
    fmt: AnnounceFormat,
    description_fmt: DescriptionFormat,
    *,
    warn_no_uploads: bool,
) -> list[Issue]:
    """告知文の検査。uploads が無い警告は、投稿前の check で毎回出ないよう呼ぶ側で選ぶ。"""
    announce = config.announce or Announce()
    issues: list[Issue] = []

    uploads = [classify(upload.url) for upload in config.uploads]
    found: dict[Site, int] = {}
    for upload in uploads:
        issues += upload.issues
        if upload.site is None:
            continue
        found[upload.site] = found.get(upload.site, 0) + 1
    for site, count in found.items():
        if count > 1:
            issues.append(Issue("error", f"uploads に {SITE_NAMES[site]} の URL が {count} つあります"))
        if site not in fmt.sites:
            wanted = {**fmt.sites, site: SITE_NAMES[site]}
            example = ", ".join(
                f"{key} = {json.dumps(name, ensure_ascii=False)}" for key, name in wanted.items()
            )
            issues.append(
                Issue(
                    "error",
                    f"ユーザー設定の announce.sites に {site} がありません"
                    f"（書くと既定は置き換わるので、例: sites = {{ {example} }}）",
                )
            )
    if not uploads and warn_no_uploads:
        issues.append(Issue("warning", "リンクがありません（投稿した動画の URL を [[uploads]] に書きます）"))

    for tag in announce.hashtags:
        if reason := hashtag_error(tag):
            issues.append(Issue("error", f"announce.hashtags の {tag!r}: {reason}"))

    if "work" in fmt.order and "{singers}" in fmt.work and not singers(config, description_fmt):
        roles = ", ".join(description_fmt.singer_roles)
        issues.append(
            Issue(
                "warning",
                f"告知文の {{singers}} に入る人がいません（roles に {roles} を持つ credits が無い）",
            )
        )

    try:
        # リンクが無いと render は link の書式を使わないので、投稿前にも書式の誤りに気づけるよう先に試す
        format_setting(fmt.link, "ユーザー設定の announce.link", site="", url="")
        text = render(config, fmt, description_fmt)
    except ConfigError as e:
        issues.append(Issue("error", str(e)))
        return issues
    if (length := weight(text)) > fmt.max_weight:
        issues.append(
            Issue(
                "warning",
                f"告知文の長さが {length} で、{fmt.max_weight} を超えています"
                "（X では「さらに表示」に折りたたまれます）",
            )
        )
    return issues
