"""字幕の行の幅を概算し、画面からはみ出しそうな行を見つける。

libass は既定（VSFilter 互換）では空白の位置でしか自動改行しないので、空白の無い日本語の長い行は
折り返されずに画面の外へはみ出す。フォントの文字送り幅から行の幅を概算して、事前に警告する。

libass はフォントの usWinAscent + usWinDescent がフォントサイズと同じ高さになるよう拡大する。
その比率で文字送り幅を px に換算すると、実際の描画と 1〜2% の誤差で一致する。
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any

import pysubs2
from fontTools.ttLib import TTCollection, TTFont

from utavideo import fonts, subs

_WRAP_TAG = re.compile(r"\\q([0-3])")
# 幅に効く上書きタグ。\fs が \fscx・\fsp を先取りしないよう、長いものを前に置く
_FORMAT_TAG = re.compile(r"\\(fn|fscx|fsp|fs|r)([^\\}]*)")
# 1文字、または改行 \N \n と固定幅空白 \h
_TOKEN = re.compile(r"\\[Nnh]|.", re.DOTALL)
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


@dataclass(frozen=True)
class _Format:
    """1文字を描くときの書式。"""

    fontname: str
    fontsize: float
    scale_x: float
    spacing: float

    @classmethod
    def of(cls, style: pysubs2.SSAStyle) -> "_Format":
        return cls(style.fontname, style.fontsize, style.scalex, style.spacing)


def _number(value: str, current: float, base: float) -> float:
    if not value:
        return base  # 引数の無いタグ（\fs など）は基本スタイルの値に戻す
    try:
        return float(value)
    except ValueError:  # \fscy150 のように、幅に効かないタグを先取りしてしまった場合
        return current


def _apply_tags(
    block: str, current: _Format, base: _Format, styles: Mapping[str, pysubs2.SSAStyle]
) -> _Format:
    for name, raw in _FORMAT_TAG.findall(block):
        value = raw.strip()
        if name == "r":
            style = styles.get(value)
            current = base if style is None else _Format.of(style)
        elif name == "fn":
            current = replace(current, fontname=value or base.fontname)
        elif name == "fs":
            current = replace(current, fontsize=_number(value, current.fontsize, base.fontsize))
        elif name == "fscx":
            current = replace(current, scale_x=_number(value, current.scale_x, base.scale_x))
        elif name == "fsp":
            current = replace(current, spacing=_number(value, current.spacing, base.spacing))
    return current


def _units(
    text: str, base: _Format, styles: Mapping[str, pysubs2.SSAStyle], wrap: int
) -> list[list[tuple[str, _Format]]]:
    """折り返せない塊ごとに、(書式が続く間の文字列, その書式) の並びを返す。

    WrapStyle 2 以外は空白でも折り返せる。固定幅空白 \\h は折り返しの対象にしない。
    """
    breaks = {"\\N", "\\n"} if wrap == 2 else {"\\N", "\\n", " "}
    units: list[list[tuple[str, _Format]]] = [[]]
    current = base
    for part in subs.OVERRIDE_BLOCK.split(text):
        if part.startswith("{") and part.endswith("}"):
            current = _apply_tags(part, current, base, styles)
            continue
        for token in _TOKEN.findall(part):
            if token in breaks:
                units.append([])
                continue
            unit = units[-1]
            char = "\u00a0" if token == "\\h" else token
            if unit and unit[-1][1] == current:
                unit[-1] = (unit[-1][0] + char, current)
            else:
                unit.append((char, current))
    return units


def overflows(script: pysubs2.SSAFile, lookup: Callable[[str], Sequence[Path]]) -> list[subs.Issue]:
    """表示幅（PlayResX から左右の余白を引いたもの）を超えそうな行の警告。

    \\pos / \\move の行と、フォントの分からない文字を含む行は対象外。上書きタグのうち
    \\fs・\\fn・\\fscx・\\fsp・\\r は概算に反映するが、\\bord（縁取りの太さ）と
    縦書き（@ 付きフォント）は反映しない。
    """
    res = subs.play_res(script)
    if res is None:
        return []
    try:
        default_wrap = int(script.info.get("WrapStyle", "0"))
    except ValueError:
        default_wrap = 0

    @cache
    def metrics_of(fontname: str) -> tuple[FontMetrics, ...]:
        return tuple(m for p in lookup(fontname) if (m := load_metrics(p, fontname)))

    def measure(unit: list[tuple[str, _Format]]) -> float:
        """塊の幅。フォントが複数見つかったときは、いちばん広いもので見積もる。"""
        return sum(
            max(
                m.text_width(run, size=fmt.fontsize, scale_x=fmt.scale_x, spacing=fmt.spacing)
                for m in metrics_of(fmt.fontname)
            )
            for run, fmt in unit
        )

    issues: list[subs.Issue] = []
    for event in subs.dialogues(script):
        style = script.styles.get(event.style)
        if style is None or subs.POS_TAG.search(event.text):
            continue
        wrap_tags = _WRAP_TAG.findall(event.text)
        wrap = int(wrap_tags[-1]) if wrap_tags else default_wrap
        units = _units(event.text, _Format.of(style), script.styles, wrap)
        if any(not metrics_of(fmt.fontname) for unit in units for _, fmt in unit):
            continue  # フォントの見つからない文字があるので測れない
        width = max(measure(unit) for unit in units) + 2 * style.outline

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
    target = fonts.match_key(family)
    return any(
        record.nameID in _NAME_IDS and fonts.match_key(record.toUnicode(errors="ignore").strip()) == target
        for record in font["name"].names
    )
