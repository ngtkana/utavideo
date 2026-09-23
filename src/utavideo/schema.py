"""ProjectConfig の JSON Schema（TOML エディタの補完・検証用）を作る。"""

import copy
import json
from importlib import resources
from pathlib import Path
from typing import Any

from utavideo.config import ProjectConfig

SCHEMA_FILENAME = "project-config.schema.json"


def _inline_refs(node: Any, defs: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    """$ref を $defs の中身で置き換える。

    taplo（Even Better TOML / Neovim の LSP）は $ref と同じ階層にある additionalProperties
    などの兄弟キーワードを見ないため、展開しないと [song] のようなネストした表で
    未知のキーの検出が効かない。
    """
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name in seen:
                raise ValueError(f"$defs が循環参照しています: {name}")
            resolved = _inline_refs(copy.deepcopy(defs[name]), defs, (*seen, name))
            siblings = _inline_refs({k: v for k, v in node.items() if k != "$ref"}, defs, seen)
            return {**resolved, **siblings}
        return {k: _inline_refs(v, defs, seen) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs, seen) for v in node]
    return node


def project_config_schema() -> dict[str, Any]:
    """utavideo.toml の補完・検証に使う JSON Schema。"""
    schema = ProjectConfig.model_json_schema(mode="validation")
    return _inline_refs(schema, schema.get("$defs", {}))


def dump_schema(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def schema_path() -> Path:
    """パッケージに同梱したスキーマファイルの絶対パス。"""
    return Path(str(resources.files("utavideo").joinpath("templates", SCHEMA_FILENAME)))
