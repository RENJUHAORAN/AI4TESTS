from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schema import validate_or_raise
from .models import (
    SCHEMA_VERSION,
    load_json,
    new_run_id,
    normalize_route,
    utc_now,
    write_json,
)
from .schema import COVERAGE_SCHEMA_PATH


def build_coverage(
    reconciliation_path: str | Path,
    catalog_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    reconciliation = _load(reconciliation_path, "reconciliation.json")
    catalog = _load(catalog_path, "process-catalog.json")
    records = list(reconciliation.get("records", []))
    processes = list(catalog.get("processes", []))

    source_paths = {
        normalize_route(str(record.get("path", "/")))
        for record in records
        if record.get("source")
    }
    matched_paths = {
        normalize_route(str(record.get("path", "/")))
        for record in records
        if record.get("status") in {"matched", "conflict", "blocked"}
        and record.get("runtimePages")
    }
    runtime_paths = {
        normalize_route(str(page.get("path", "/")))
        for record in records
        for page in record.get("runtimePages", [])
    }
    roles = sorted(
        {
            str(page.get("role", "anonymous"))
            for record in records
            for page in record.get("runtimePages", [])
        }
    )
    runtime_graph = _sibling_runtime_graph(reconciliation_path)
    runtime_roles = {
        str(role.get("name"))
        for role in runtime_graph.get("roles", [])
        if role.get("name")
    }
    observed_roles = set(roles)
    role_total = len(runtime_roles | observed_roles)
    role_covered = len(runtime_roles & observed_roles) if runtime_roles else len(
        observed_roles
    )

    process_metrics: list[dict[str, Any]] = []
    total_steps = 0
    observed_steps = 0
    for process in processes:
        steps = list(process.get("steps", []))
        matched = sum(step.get("status") == "matched" for step in steps)
        process_steps = len(steps)
        total_steps += process_steps
        observed_steps += matched
        process_metrics.append(
            {
                "id": process.get("id"),
                "title": process.get("title"),
                "status": process.get("status"),
                "roleCount": len(process.get("roles", [])),
                "steps": process_steps,
                "matchedSteps": matched,
                "ratio": round(matched / process_steps, 4)
                if process_steps
                else 0.0,
            }
        )

    transitions = list(runtime_graph.get("transitions", []))
    supported_transitions = [
        transition
        for transition in transitions
        if normalize_route(str(transition.get("fromPath", "/"))) in source_paths
        and normalize_route(str(transition.get("toPath", "/"))) in source_paths
    ]

    value = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": new_run_id("coverage"),
        "generatedAt": utc_now(),
        "status": "evidence-based",
        "routeCoverage": _metric(
            len(matched_paths),
            len(source_paths),
            "运行时可达源码路由 / 源码路由",
        ),
        "runtimeDiscovery": {
            "runtimePaths": len(runtime_paths),
            "runtimeOnlyPaths": len(runtime_paths - source_paths),
            "ratio": round(
                len(runtime_paths - source_paths) / len(runtime_paths),
                4,
            )
            if runtime_paths
            else 0.0,
        },
        "transitionCoverage": _metric(
            len(supported_transitions),
            len(transitions),
            "源码两端均声明的运行时跳转 / 已观测跳转",
        ),
        "roleCoverage": _metric(
            role_covered,
            role_total,
            "实际产生页面的角色 / 配置与运行角色并集",
        ),
        "processCoverage": _metric(
            observed_steps,
            total_steps,
            "已对账流程步骤 / 全部候选流程步骤",
        ),
        "processBreakdown": process_metrics,
        "gaps": _coverage_gaps(records, processes),
        "caveats": [
            "覆盖率衡量证据覆盖，不等于需求覆盖率或业务正确率。",
            "source-only 通常来自权限、数据、入口或静态解析遗漏。",
            "runtime-only 必须结合源码和接口证据人工定性。",
            "未授权的高风险写流程只记录为 blocked/未覆盖，不自动执行。",
        ],
    }
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    validate_or_raise(
        value,
        COVERAGE_SCHEMA_PATH,
        "Coverage",
    )
    write_json(output / "coverage.json", value)
    return {**value, "outputDir": str(output)}


def _metric(covered: int, total: int, basis: str) -> dict[str, Any]:
    return {
        "covered": covered,
        "total": total,
        "ratio": round(covered / total, 4) if total else 0.0,
        "basis": basis,
    }


def _coverage_gaps(
    records: list[dict[str, Any]],
    processes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for record in records:
        if record.get("status") in {"source-only", "runtime-only", "conflict", "blocked"}:
            gaps.append(
                {
                    "type": "route",
                    "id": record.get("id"),
                    "path": record.get("path"),
                    "status": record.get("status"),
                    "reasons": record.get("reasons", []),
                }
            )
    for process in processes:
        if process.get("status") != "matched":
            gaps.append(
                {
                    "type": "process",
                    "id": process.get("id"),
                    "title": process.get("title"),
                    "status": process.get("status"),
                }
            )
    return gaps


def _sibling_runtime_graph(path: str | Path) -> dict[str, Any]:
    candidate = Path(path).resolve()
    directory = candidate if candidate.is_dir() else candidate.parent
    runtime_path = directory / "runtime-graph.json"
    if not runtime_path.is_file():
        return {}
    return load_json(runtime_path)


def _load(path: str | Path, preferred_name: str) -> dict[str, Any]:
    candidate = Path(path).resolve()
    if candidate.is_dir():
        candidate = candidate / preferred_name
    if not candidate.is_file():
        raise FileNotFoundError(f"证据文件不存在: {candidate}")
    return load_json(candidate)
