"""ドキュメントがコードと食い違っていないかを確かめる。"""

import re
import typing
from pathlib import Path

import pytest
import typer.main
from pydantic import BaseModel

from utavideo.cli import app
from utavideo.config import ProjectConfig, UserConfig

ROOT = Path(__file__).parents[1]
DOCS = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").rglob("*.md"))]


def _doc(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def test_commands_doc_lists_every_command_and_option() -> None:
    doc = _doc("commands.md")
    for name, command in typer.main.get_group(app).commands.items():
        assert f"utavideo {name}" in doc
        for param in command.params:
            if param.param_type_name == "option":
                for opt in param.opts:
                    assert f"`{opt}" in doc, f"{name} の {opt}"


def _section(doc: str, heading: str) -> str:
    """見出しが heading で始まる節の、次の見出しまでの本文。"""
    lines = doc.splitlines()
    starts = [
        i for i, line in enumerate(lines) if line.startswith("#") and line.lstrip("# ").startswith(heading)
    ]
    assert len(starts) == 1, f"見出し {heading!r} が {len(starts)} 個"
    end = next((j for j in range(starts[0] + 1, len(lines)) if lines[j].startswith("#")), len(lines))
    return "\n".join(lines[starts[0] + 1 : end])


def _nested_model(annotation: object) -> tuple[type[BaseModel], bool] | None:
    """設定項目が表（[x]）か表の配列（[[x]]）なら、そのモデルと、配列かどうか。"""
    for candidate in (annotation, *typing.get_args(annotation)):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate, typing.get_origin(annotation) is tuple
    return None


def _assert_documented(doc: str, model: type[BaseModel], heading: str, prefix: str, seen: set[type]) -> None:
    body = _section(doc, heading)
    for name, info in model.model_fields.items():
        nested = _nested_model(info.annotation)
        if nested is None or nested[0] in seen:  # 説明済みの表は、項目名だけ載っていればよい
            assert f"| `{name}` |" in body, f"{heading} の {name}"
            continue
        sub, is_array = nested
        seen.add(sub)
        _assert_documented(doc, sub, f"{prefix}[[{name}]]" if is_array else f"{prefix}[{name}]", prefix, seen)


def test_config_reference_lists_every_field() -> None:
    doc = _doc("config-reference.md")
    seen: set[type] = set()
    for name, info in ProjectConfig.model_fields.items():
        nested = _nested_model(info.annotation)
        assert nested is not None, name
        seen.add(nested[0])
        _assert_documented(doc, nested[0], f"[[{name}]]" if nested[1] else f"[{name}]", "", seen)
    _assert_documented(doc, UserConfig, "ユーザー設定（", "ユーザー設定の ", seen)


def test_config_reference_lists_every_environment_variable() -> None:
    doc = _doc("config-reference.md")
    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "utavideo").glob("*.py"))
    names = set(re.findall(r'(?:os\.environ\.get|_xdg)\("([A-Z_]+)"', source))
    assert names  # 抽出の正規表現が壊れていたら、何も確かめずに通ってしまう
    for name in names:
        assert name in doc, name


def _anchor(heading: str) -> str:
    # GitHub の見出しのアンカー: 小文字にし、記号を除き、空白を - にする
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    for target in re.findall(r"\]\(([^)\s]+)\)", doc.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://")):
            continue
        file, _, anchor = target.partition("#")
        dest = (doc.parent / file).resolve() if file else doc
        assert dest.exists(), target
        if anchor:
            headings = re.findall(r"^#+ (.+)$", dest.read_text(encoding="utf-8"), re.MULTILINE)
            assert anchor in {_anchor(h) for h in headings}, target
