"""字幕の行の幅を概算し、画面からはみ出しそうな行を見つける。

libass は既定（VSFilter 互換）では空白の位置でしか自動改行しないので、空白の無い日本語の長い行は
折り返されずに画面の外へはみ出す。フォントの文字送り幅から行の幅を概算して、事前に警告する。

libass はフォントの usWinAscent + usWinDescent がフォントサイズと同じ高さになるよう拡大する。
その比率で文字送り幅を px に換算すると、実際の描画と 1〜2% の誤差で一致する。
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pysubs2
from fontTools.ttLib import TTCollection, TTFont

from utavideo import subs

_OVERRIDE_BLOCK = re.compile(r"\{[^}]*\}")
_POS_TAG = re.compile(r"\\(?:pos|move)\s*\(")
_WRAP_TAG = re.compile(r"\\q([0-3])")
_NAME_IDS = frozenset({1, 4, 6, 16})


@dataclass(frozen=True)
class FontMetrics:
    cell_height: int
    fallback_advance: int
    advances: dict[int, int]

    def text_width(self, text: str, *, size: float, scale_x: float, spacing: float) -> float:
        units = sum(self.advances.get(ord(ch), self.fallback_advance) for ch in text)
        return (units * size / self.cell_height + spacing * len(text)) * scale_x / 100


@cache
def load_metrics(path: Path, family: str) -> FontMetrics | None:
    """フォントの文字送り幅。TTC はファミリー名が一致するフォントを使う。読めなければ None。"""
    try:
        if path.suffix.lower() in {".ttc", ".otc"}:
            container = TTCollection(path, lazy=True)
            candidates = list(container.fonts)
        else:
            container = TTFont(path, lazy=True)
            candidates = [container]
        try:
            font = next((f for f in candidates if _has_name(f, family)), candidates[0])
            # fontTools のテーブルは属性が型に現れないので Any で受ける
            head: Any = font["head"]
            os2: Any = font["OS/2"]
            hmtx: Any = font["hmtx"]
            units_per_em = head.unitsPerEm
            advances = {cp: hmtx[glyph][0] for cp, glyph in (font.getBestCmap() or {}).items()}
            cell_height = (os2.usWinAscent + os2.usWinDescent) or units_per_em
            # フォントに無い文字は別のフォントで描かれるので、全角1文字分とみなす
            return FontMetrics(cell_height, units_per_em, advances)
        finally:
            container.close()
    except Exception:  # 壊れた・未対応のフォントは概算の対象から外すだけ
        return None


def overflows(script: pysubs2.SSAFile, lookup: Callable[[str], Sequence[Path]]) -> list[subs.Issue]:
    """表示幅（PlayResX から左右の余白を引いたもの）を超えそうな行の警告。\\pos の行は対象外。"""
    res = subs.play_res(script)
    if res is None:
        return []
    try:
        default_wrap = int(script.info.get("WrapStyle", "0"))
    except ValueError:
        default_wrap = 0

    issues: list[subs.Issue] = []
    for event in subs.dialogues(script):
        style = script.styles.get(event.style)
        if style is None or _POS_TAG.search(event.text):
            continue
        metrics = [m for path in lookup(style.fontname) if (m := load_metrics(path, style.fontname))]
        if not metrics:
            continue

        def measure(
            text: str, style: pysubs2.SSAStyle = style, metrics: list[FontMetrics] = metrics
        ) -> float:
            width = max(
                m.text_width(text, size=style.fontsize, scale_x=style.scalex, spacing=style.spacing)
                for m in metrics
            )
            return width + 2 * style.outline

        wrap_tags = _WRAP_TAG.findall(event.text)
        wrap = int(wrap_tags[-1]) if wrap_tags else default_wrap
        text = _OVERRIDE_BLOCK.sub("", event.text).replace("\\h", "\u00a0")
        lines = text.replace("\\n", "\\N" if wrap == 2 else " ").split("\\N")
        # WrapStyle 2 以外は空白で折り返せるので、空白で区切った塊ごとに収まるかを見る
        units = lines if wrap == 2 else [run for line in lines for run in line.split(" ")]
        width = max(map(measure, units), default=0.0)

        available = res[0] - (event.marginl or style.marginl) - (event.marginr or style.marginr)
        if width > available:
            issues.append(
                subs.Issue(
                    "warning",
                    f"{subs.describe(event)} が画面からはみ出しそうです"
                    f"（推定 {width:.0f}px ＞ 表示幅 {available}px）。\\N で改行してください",
                )
            )
    return issues


def _has_name(font: TTFont, family: str) -> bool:
    target = family.casefold()
    return any(
        record.nameID in _NAME_IDS and record.toUnicode(errors="ignore").strip().casefold() == target
        for record in font["name"].names
    )
