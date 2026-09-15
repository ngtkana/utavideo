"""ドキュメントがコードと食い違っていないかを確かめる。"""

import re
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


def test_config_reference_lists_every_field() -> None:
    doc = _doc("config-reference.md")
    for section, info in ProjectConfig.model_fields.items():
        model = info.annotation
        assert isinstance(model, type) and issubclass(model, BaseModel)
        assert f"## [{section}]" in doc
        for field in model.model_fields:
            assert f"| `{field}` |" in doc, f"{section}.{field}"
    for field in UserConfig.model_fields:
        assert f"| `{field}` |" in doc, field


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
