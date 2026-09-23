"""同梱の JSON Schema が ProjectConfig と食い違っていないかを確かめる。"""

from utavideo.schema import dump_schema, project_config_schema, schema_path


def test_schema_file_matches_the_model() -> None:
    committed = schema_path().read_text(encoding="utf-8")
    regenerated = dump_schema(project_config_schema())
    assert committed == regenerated, (
        "ProjectConfig を変えたら uv run python scripts/generate_schema.py で再生成する"
    )
