from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from ui_test_poc.schema import (
    SCHEMAS_DIR,
    format_schema_errors,
    validate_instance,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="校验 Codex 观察结果和快照证据",
    )
    parser.add_argument("result_path")
    parser.add_argument("--require-snapshot", action="store_true")
    options = parser.parse_args()

    input_path = Path(options.result_path).resolve()
    try:
        value = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"无法读取结果文件: {error}")
        return 1

    errors = validate_instance(
        value,
        SCHEMAS_DIR / "codex-run-result.schema.json",
    )
    if errors:
        print("\n".join(format_schema_errors(errors)))
        return 1

    if options.require_snapshot:
        snapshot = value["evidence"].get("snapshot")
        if not snapshot or snapshot == "inline-snapshot":
            print("MCP 烟测必须记录真实快照文件，不能使用 inline-snapshot")
            return 1

        snapshot_path = (ROOT / snapshot).resolve()
        try:
            snapshot_path.relative_to(ROOT)
        except ValueError:
            print(f"快照文件必须位于工作区内: {snapshot_path}")
            return 1
        if not snapshot_path.is_file():
            print(f"快照文件不存在: {snapshot_path}")
            return 1

    print(
        json.dumps(
            {
                "valid": True,
                "observedStatus": value["observedStatus"],
                "authoritativeStatus": value["authoritativeStatus"],
                "snapshot": value["evidence"].get("snapshot"),
                "steps": len(value["steps"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

