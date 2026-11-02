from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from ..schema import validate_or_raise
from .models import (
    SCHEMA_VERSION,
    load_json,
    new_run_id,
    normalize_route,
    stable_id,
    utc_now,
    write_json,
)
from .schema import PROCESS_CATALOG_SCHEMA_PATH

PROCESS_KEYWORDS = (
    ("payment", re.compile(r"(pay|payment|checkout|refund)", re.I)),
    ("order", re.compile(r"(order|cart|purchase|submit)", re.I)),
    ("permission", re.compile(r"(role|permission|authorize|approve)", re.I)),
    ("authentication", re.compile(r"(login|logout|auth|signin|register)", re.I)),
    ("search", re.compile(r"(search|query|filter|list)", re.I)),
    ("settings", re.compile(r"(setting|profile|account|preference)", re.I)),
)


def build_process_catalog(
    reconciliation_path: str | Path,
    output_dir: str | Path,
    *,
    maxDepth: int = 6,
) -> dict[str, Any]:
    reconciliation = _load_path(
        reconciliation_path,
        "reconciliation.json",
    )
    runtime = _optional_sibling(
        reconciliation_path,
        "runtime-graph.json",
    )
    routes = _route_map(reconciliation)
    transitions = _runtime_transitions(runtime)
    api_calls = _runtime_api_calls(runtime)
    processes = _build_runtime_processes(
        routes,
        transitions,
        api_calls,
        max_depth=maxDepth,
    )
    covered_paths = {
        str(step["path"])
        for process in processes
        for step in process["steps"]
    }
    for record in reconciliation.get("records", []):
        if record.get("status") != "source-only":
            continue
        path = normalize_route(str(record.get("path", "/")))
        if path in covered_paths:
            continue
        processes.append(_source_only_process(record))
        covered_paths.add(path)

    processes = sorted(processes, key=lambda item: (item["category"], item["id"]))
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    process_dir = output / "processes"
    process_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    for process in processes:
        process_file = process_dir / f"{process['id']}.yaml"
        process_file.write_text(
            yaml.safe_dump(
                process,
                allow_unicode=True,
                sort_keys=False,
                width=100,
            ),
            encoding="utf-8",
        )
        files.append(process_file.relative_to(output).as_posix())

    run_id = new_run_id("catalog")
    value = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "generatedAt": utc_now(),
        "status": "review-required",
        "sourceReconciliationRunId": reconciliation.get("runId"),
        "maxDepth": maxDepth,
        "processes": processes,
        "processFiles": files,
        "summary": {
            "processes": len(processes),
            "matchedProcesses": sum(
                item["status"] == "matched" for item in processes
            ),
            "sourceOnlyProcesses": sum(
                item["status"] == "source-only" for item in processes
            ),
            "runtimeOnlyProcesses": sum(
                item["status"] == "runtime-only" for item in processes
            ),
            "conflictProcesses": sum(
                item["status"] == "conflict" for item in processes
            ),
            "blockedProcesses": sum(
                item["status"] == "blocked" for item in processes
            ),
        },
        "caveats": [
            "流程为基于源码与只读运行时证据生成的候选目录，不是完整需求规格。",
            "未覆盖的写操作、权限分支和异常分支必须通过 Test Card 人工补充。",
            "流程存在不等于业务测试通过；权威结论仍由 Test Contract Runner 生成。",
        ],
    }
    validate_or_raise(
        value,
        PROCESS_CATALOG_SCHEMA_PATH,
        "Process Catalog",
    )
    write_json(output / "process-catalog.json", value)
    return {**value, "outputDir": str(output)}


def _build_runtime_processes(
    routes: dict[str, dict[str, Any]],
    transitions: list[dict[str, Any]],
    api_calls: list[dict[str, Any]],
    *,
    max_depth: int,
) -> list[dict[str, Any]]:
    adjacency: dict[tuple[str, str], list[str]] = defaultdict(list)
    role_nodes: dict[str, set[str]] = defaultdict(set)
    for transition in transitions:
        role = str(transition.get("role", "anonymous"))
        source = normalize_route(str(transition.get("fromPath", "/")))
        target = normalize_route(str(transition.get("toPath", "/")))
        if target not in adjacency[(role, source)]:
            adjacency[(role, source)].append(target)
        role_nodes[role].update({source, target})

    chains: set[tuple[str, ...]] = set()
    for role, nodes in role_nodes.items():
        incoming = {
            target
            for source in nodes
            for target in adjacency[(role, source)]
        }
        roots = sorted(nodes - incoming) or sorted(nodes)
        for root in roots:
            for path in _bounded_paths(adjacency, role, root, max_depth):
                if len(path) >= 2:
                    chains.add(tuple(path))

    processes: list[dict[str, Any]] = []
    for chain in sorted(chains):
        roles = sorted(
            role
            for role in role_nodes
            if all(
                right in adjacency[(role, left)]
                for left, right in zip(chain, chain[1:], strict=False)
            )
        )
        steps = [
            _step_record(path, index + 1, routes.get(path))
            for index, path in enumerate(chain)
        ]
        status = _aggregate_route_status(chain, routes)
        category = _classify_process(" -> ".join(chain))
        dependencies = _api_dependencies(api_calls, set(chain), roles)
        processes.append(
            {
                "schemaVersion": SCHEMA_VERSION,
                "id": stable_id("PROC", chain),
                "title": _title_for_process(category, chain),
                "status": status,
                "category": category,
                "roles": roles,
                "preconditions": _preconditions(category, roles),
                "entryPath": chain[0],
                "outcome": {
                    "type": "observed-state",
                    "path": chain[-1],
                    "assertion": None,
                },
                "steps": steps,
                "branches": [],
                "apiDependencies": dependencies,
                "evidence": _process_evidence(chain, routes),
                "coverage": {
                    "stepsObserved": len(chain),
                    "stepsInferred": 0,
                    "ratio": 1.0,
                },
                "risk": {
                    "level": _risk_level(category),
                    "destructive": category in {"payment", "permission"},
                    "approvalRequired": category in {"payment", "permission"},
                },
                "confidence": 0.65 if status == "matched" else 0.5,
            }
        )
    return processes


def _bounded_paths(
    adjacency: dict[tuple[str, str], list[str]],
    role: str,
    root: str,
    max_depth: int,
) -> list[list[str]]:
    results: list[list[str]] = []

    def visit(path: list[str]) -> None:
        current = path[-1]
        children = [
            child
            for child in adjacency[(role, current)]
            if child not in path
        ]
        if not children or len(path) >= max_depth:
            results.append(path)
            return
        for child in children:
            visit([*path, child])

    visit([root])
    return results


def _source_only_process(record: dict[str, Any]) -> dict[str, Any]:
    path = normalize_route(str(record.get("path", "/")))
    category = _classify_process(path)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": stable_id("PROC", "source-only", path),
        "title": _title_for_process(category, [path]),
        "status": "source-only",
        "category": category,
        "roles": [],
        "preconditions": [
            "该页面只在源码中发现，运行时未到达",
            "需补充角色、数据、入口或权限前置条件",
        ],
        "entryPath": path,
        "outcome": {
            "type": "unverified",
            "path": path,
            "assertion": None,
        },
        "steps": [_step_record(path, 1, record.get("source"))],
        "branches": [],
        "apiDependencies": [],
        "evidence": [
            {
                "type": "source",
                "reference": record.get("source"),
                "confidence": record.get("confidence", 0.4),
            }
        ],
        "coverage": {
            "stepsObserved": 0,
            "stepsInferred": 1,
            "ratio": 0.0,
        },
        "risk": {
            "level": _risk_level(category),
            "destructive": category in {"payment", "permission"},
            "approvalRequired": category in {"payment", "permission"},
        },
        "confidence": 0.35,
    }


def _step_record(
    path: str,
    order: int,
    route: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "order": order,
        "path": path,
        "name": (
            route.get("name")
            if route and route.get("name")
            else path
        ),
        "status": (
            "matched"
            if route and route.get("status") in {"matched", "source-only"}
            else "runtime-only"
        ),
        "source": route.get("source") if route else None,
    }


def _aggregate_route_status(
    chain: tuple[str, ...],
    routes: dict[str, dict[str, Any]],
) -> str:
    statuses = {
        str(routes.get(path, {}).get("status", "runtime-only"))
        for path in chain
    }
    for candidate in ("conflict", "blocked", "runtime-only", "source-only"):
        if candidate in statuses:
            return candidate
    return "matched"


def _classify_process(text: str) -> str:
    # 以业务流程的目标页为主，避免“登录后搜索”被误归为认证流程。
    segments = [segment.strip() for segment in text.split("->") if segment.strip()]
    for segment in reversed(segments or [text]):
        for name, pattern in PROCESS_KEYWORDS:
            if pattern.search(segment):
                return name
    return "general"


def _risk_level(category: str) -> str:
    if category in {"payment", "permission"}:
        return "high"
    if category == "order":
        return "normal"
    return "read-only"


def _title_for_process(category: str, chain: list[str] | tuple[str, ...]) -> str:
    labels = {
        "payment": "支付与退款候选流程",
        "order": "订单提交候选流程",
        "permission": "权限与审批候选流程",
        "authentication": "登录认证候选流程",
        "search": "查询检索候选流程",
        "settings": "账户设置候选流程",
        "general": "页面导航候选流程",
    }
    return f"{labels.get(category, labels['general'])}: {' -> '.join(chain)}"


def _preconditions(category: str, roles: list[str]) -> list[str]:
    values = [f"使用角色: {', '.join(roles) or '未确认'}"]
    values.append("按运行时证据补充业务数据和前置状态")
    if category in {"payment", "permission"}:
        values.append("高风险流程必须人工授权后执行")
    return values


def _api_dependencies(
    calls: list[dict[str, Any]],
    paths: set[str],
    roles: list[str],
) -> list[dict[str, Any]]:
    dependencies: dict[tuple[str, str], dict[str, Any]] = {}
    for call in calls:
        path = normalize_route(str(call.get("pagePath", "/")))
        if path not in paths:
            continue
        if roles and call.get("role") not in roles:
            continue
        key = (
            str(call.get("method", "GET")),
            str(call.get("url", "")),
        )
        dependencies[key] = {
            "method": key[0],
            "url": key[1],
            "classification": call.get("classification", "read"),
            "pagePath": path,
        }
    return sorted(
        dependencies.values(),
        key=lambda item: (item["pagePath"], item["method"], item["url"]),
    )


def _process_evidence(
    chain: tuple[str, ...],
    routes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for path in chain:
        route = routes.get(path)
        if route and route.get("source"):
            evidence.append(
                {
                    "type": "source",
                    "path": path,
                    "reference": route["source"],
                }
            )
        if route:
            evidence.append(
                {
                    "type": "runtime",
                    "path": path,
                    "pages": route.get("runtimePages", []),
                }
            )
    return evidence


def _route_map(
    reconciliation: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    for record in reconciliation.get("records", []):
        path = normalize_route(str(record.get("path", "/")))
        routes.setdefault(
            path,
            {
                **record,
                "name": (
                    record.get("source", {}).get("name")
                    if record.get("source")
                    else path
                ),
            },
        )
    return routes


def _runtime_transitions(
    runtime: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    return list((runtime or {}).get("transitions", []))


def _runtime_api_calls(
    runtime: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    return list((runtime or {}).get("apiCalls", []))


def _load_path(path: str | Path, preferred_name: str) -> dict[str, Any]:
    candidate = Path(path).resolve()
    if candidate.is_dir():
        candidate = candidate / preferred_name
    if not candidate.is_file():
        raise FileNotFoundError(f"证据文件不存在: {candidate}")
    return load_json(candidate)


def _optional_sibling(
    path: str | Path,
    name: str,
) -> dict[str, Any] | None:
    candidate = Path(path).resolve()
    directory = candidate if candidate.is_dir() else candidate.parent
    file_path = directory / name
    if not file_path.is_file():
        return None
    return load_json(file_path)
