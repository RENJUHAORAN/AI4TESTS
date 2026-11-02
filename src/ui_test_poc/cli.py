from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Sequence

from .contract import ContractError, load_contract
from .discovery.catalog import build_process_catalog
from .discovery.config import run_discovery
from .discovery.coverage import build_coverage
from .discovery.reconcile import reconcile_graphs
from .discovery.runtime_index import explore_runtime, load_runtime_config
from .discovery.source_index import build_source_graph
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


def build_discovery_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="ui-test discover",
        description="发现前端路由、运行时流程、证据对账和覆盖率",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    source_parser = subparsers.add_parser(
        "source",
        help="静态读取前端路由和链接，不执行前端构建脚本",
    )
    source_parser.add_argument("--repo", required=True, help="前端源码仓库")
    source_parser.add_argument("--output", required=True, help="证据输出目录")
    source_parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="包含文件正则，可重复",
    )
    source_parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="排除文件正则，可重复",
    )

    runtime_parser = subparsers.add_parser(
        "runtime",
        help="使用只读 Playwright 采集页面、跳转和网络证据",
    )
    runtime_parser.add_argument("--config", required=True, help="发现配置 YAML")
    runtime_parser.add_argument("--source-index", help="源码索引目录或文件")
    runtime_parser.add_argument("--output", required=True, help="证据输出目录")
    runtime_parser.add_argument("--headed", action="store_true")

    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="对账源码路由与运行时页面",
    )
    reconcile_parser.add_argument("--source", required=True)
    reconcile_parser.add_argument("--runtime", required=True)
    reconcile_parser.add_argument("--output", required=True)

    catalog_parser = subparsers.add_parser(
        "catalog",
        help="从对账证据生成业务流程候选目录",
    )
    catalog_parser.add_argument("--reconciliation", required=True)
    catalog_parser.add_argument("--output", required=True)
    catalog_parser.add_argument("--max-depth", type=int, default=6)

    coverage_parser = subparsers.add_parser(
        "coverage",
        help="生成分维度覆盖率与缺口清单",
    )
    coverage_parser.add_argument("--reconciliation", required=True)
    coverage_parser.add_argument("--catalog", required=True)
    coverage_parser.add_argument("--output", required=True)

    all_parser = subparsers.add_parser(
        "all",
        help="按一个配置执行源码、运行时、对账、目录和覆盖率全流程",
    )
    all_parser.add_argument("--config", required=True)
    all_parser.add_argument("--output")
    all_parser.add_argument("--headed", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments[:1] == ["discover"]:
        return _discovery_main(arguments[1:])
    if arguments[:1] == ["run"]:
        arguments = arguments[1:]
    return _contract_main(arguments)


def _contract_main(argv: Sequence[str]) -> int:
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


def _discovery_main(argv: Sequence[str]) -> int:
    parser = build_discovery_parser()
    options = parser.parse_args(argv)
    try:
        if options.command == "source":
            result = build_source_graph(
                options.repo,
                options.output,
                include=options.include,
                exclude=options.exclude,
            )
            summary = {
                "runId": result["runId"],
                "status": result["status"],
                "outputDir": result["outputDir"],
                "stats": result["stats"],
                "warnings": result["warnings"],
            }
        elif options.command == "runtime":
            config = load_runtime_config(options.config)
            result = explore_runtime(
                config,
                options.output,
                source_graph_path=options.source_index,
                headless=not options.headed,
            )
            summary = _runtime_summary(result)
        elif options.command == "reconcile":
            result = reconcile_graphs(
                options.source,
                options.runtime,
                options.output,
            )
            summary = {
                "runId": result["runId"],
                "status": result["status"],
                "outputDir": result["outputDir"],
                "summary": result["summary"],
            }
        elif options.command == "catalog":
            result = build_process_catalog(
                options.reconciliation,
                options.output,
                maxDepth=options.max_depth,
            )
            summary = _catalog_summary(result)
        elif options.command == "coverage":
            result = build_coverage(
                options.reconciliation,
                options.catalog,
                options.output,
            )
            summary = _coverage_summary(result)
        else:
            result = run_discovery(
                options.config,
                output_root=options.output,
                headless=not options.headed,
            )
            summary = result
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(f"[discovery] {error}", file=sys.stderr)
        traceback.print_exc()
        return 1


def _runtime_summary(result: dict) -> dict:
    return {
        "runId": result["runId"],
        "status": result["status"],
        "outputDir": result["outputDir"],
        "stats": result["stats"],
        "warnings": result["warnings"],
    }


def _catalog_summary(result: dict) -> dict:
    return {
        "runId": result["runId"],
        "status": result["status"],
        "outputDir": result["outputDir"],
        "summary": result["summary"],
    }


def _coverage_summary(result: dict) -> dict:
    return {
        "runId": result["runId"],
        "status": result["status"],
        "outputDir": result["outputDir"],
        "routeCoverage": result["routeCoverage"],
        "transitionCoverage": result["transitionCoverage"],
        "roleCoverage": result["roleCoverage"],
        "processCoverage": result["processCoverage"],
    }


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()

