import json
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/codex-run-result.schema.json"


def walk_schema(
    node: Any,
    location: str,
    visit: Callable[[dict[str, Any], str], None],
) -> None:
    if not isinstance(node, dict):
        return

    visit(node, location)

    for name, child in node.get("properties", {}).items():
        walk_schema(
            child,
            f"{location}/properties/{name}",
            visit,
        )
    if "items" in node:
        walk_schema(node["items"], f"{location}/items", visit)
    for index, child in enumerate(node.get("anyOf", [])):
        walk_schema(child, f"{location}/anyOf/{index}", visit)
    for name, child in node.get("$defs", {}).items():
        walk_schema(child, f"{location}/$defs/{name}", visit)


def test_codex_schema_meets_strict_structured_output_rules():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []

    def inspect(node: dict[str, Any], location: str) -> None:
        if "enum" in node and "type" not in node:
            failures.append(f"{location}: enum 必须声明 type")
        if isinstance(node.get("type"), list):
            failures.append(f"{location}: 不允许 type 数组")
        for index, branch in enumerate(node.get("anyOf", [])):
            if "type" not in branch:
                failures.append(
                    f"{location}/anyOf/{index}: 分支必须提供 type"
                )
        if (
            node.get("type") == "object"
            and node.get("additionalProperties") is False
        ):
            required = sorted(node.get("required", []))
            properties = sorted(node.get("properties", {}))
            if required != properties:
                failures.append(
                    f"{location}: required 必须覆盖全部 properties"
                )

    walk_schema(schema, "#", inspect)
    assert failures == []

