#!/usr/bin/env python3
"""utavideo.toml の JSON Schema（templates/project-config.schema.json）を再生成する。

ProjectConfig を変えたら実行する: uv run python scripts/generate_schema.py
"""

from utavideo.schema import dump_schema, project_config_schema, schema_path


def main() -> None:
    schema_path().write_text(dump_schema(project_config_schema()), encoding="utf-8")


if __name__ == "__main__":
    main()
