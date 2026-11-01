from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Sequence

from .contract import ContractError, load_contract
from .runner import run_contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ui-test",
        description="执行零代码 UI Test Contract",
    )
    parser.add_argument(
        "contract_path",
        nargs="?",
        help="Contract YAML 路径",
    )
    parser.add_argument(
        "--contract",
        dest="contract_option",
        help="Contract YAML 路径",
    )
    parser.add_argument(
        "--output",
        default="artifacts/runs",
        help="证据输出根目录，默认 artifacts/runs",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="显示浏览器窗口",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)
    contract_path = options.contract_option or options.contract_path

    if not contract_path:
        parser.print_help()
        return 2

    try:
        contract, secret_values = load_contract(contract_path)
        result = run_contract(
            contract,
            secret_values=secret_values,
            output_root=options.output,
            headless=not options.headed,
        )
        print(
            json.dumps(
                {
                    "runId": result["runId"],
                    "caseId": result["caseId"],
                    "status": result["status"],
                    "durationMs": result["durationMs"],
                    "runDir": os.path.relpath(
                        result["runDir"],
                        Path.cwd(),
                    ),
                    "evidence": result["evidence"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if result["status"] == "passed" else 1
    except ContractError as error:
        print(f"[contract] {error}", file=sys.stderr)
        for detail in error.details:
            print(f"- {detail}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"[runner] {error}", file=sys.stderr)
        traceback.print_exc()
        return 1


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()

