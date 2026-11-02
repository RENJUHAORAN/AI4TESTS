from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..schema import validate_or_raise
from .models import (
    SCHEMA_VERSION,
    load_json,
    matches_route,
    new_run_id,
    normalize_route,
    stable_id,
    utc_now,
    write_json,
)
from .schema import RECONCILIATION_SCHEMA_PATH


def reconcile_graphs(
    source_path: str | Path,
    runtime_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    source = load_discovery_graph(source_path, "source-graph.json")
    runtime = load_discovery_graph(runtime_path, "runtime-graph.json")
    source_routes = list(source.get("routes", []))
    runtime_pages = list(runtime.get("pages", []))
    run_id = new_run_id("reconcile")

    records: list[dict[str, Any]] = []
    claimed_runtime_ids: set[str] = set()
    duplicate_paths = _duplicate_source_paths(source_routes)

    for route in source_routes:
        route_path = str(route.get("normalized_path") or route.get("path", "/"))
        matched_pages = _match_runtime_pages(route_path, runtime_pages)
        matched_pages = [
            page
            for page in matched_pages
            if page.get("id") not in claimed_runtime_ids
        ]
        for page in matched_pages:
            claimed_runtime_ids.add(str(page.get("id")))

        if not matched_pages:
            status = "source-only"
        elif route_path in duplicate_paths:
            status = "conflict"
        elif any(
            str(page.get("status", "")).startswith("blocked")
            for page in matched_pages
        ):
            status = "blocked"
        elif any(
            str(page.get("status", "")).startswith("http-error")
            for page in matched_pages
        ):
            status = "conflict"
        else:
            status = "matched"

        records.append(
            {
                "id": stable_id(
                    "MATCH",
                    route.get("normalized_path", route_path),
                    route.get("source", {}).get("path", ""),
                    route.get("source", {}).get("line", 0),
                    route.get("component"),
                ),
                "path": route_path,
                "status": status,
                "source": route,
                "runtimePages": matched_pages,
                "reasons": _reconciliation_reasons(
                    status,
                    route_path,
                    matched_pages,
                ),
                "confidence": _confidence(status, route, matched_pages),
            }
        )

    for page in runtime_pages:
        if page.get("id") in claimed_runtime_ids:
            continue
        path = normalize_route(str(page.get("path", "/")))
        status = (
            "blocked"
            if str(page.get("status", "")).startswith("blocked")
            else "runtime-only"
        )
        records.append(
            {
                "id": stable_id(
                    "MATCH",
                    "runtime-only",
                    page.get("role", ""),
                    path,
                ),
                "path": path,
                "status": status,
                "source": None,
                "runtimePages": [page],
                "reasons": [
                    "运行时可达，但当前源码索引未找到对应路由声明",
                    "可能是动态路由、第三方页面、权限差异或源码解析遗漏",
                ],
                "confidence": 0.45,
            }
        )

    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record["status"])
        status_counts[status] = status_counts.get(status, 0) + 1

    value = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "generatedAt": utc_now(),
        "status": "review-required",
        "sourceRunId": source.get("runId"),
        "runtimeRunId": runtime.get("runId"),
        "records": sorted(
            records,
            key=lambda item: (item["path"], item["id"]),
        ),
        "summary": {
            "sourceRoutes": len(source_routes),
            "runtimePages": len(runtime_pages),
            "matched": status_counts.get("matched", 0),
            "sourceOnly": status_counts.get("source-only", 0),
            "runtimeOnly": status_counts.get("runtime-only", 0),
            "conflict": status_counts.get("conflict", 0),
            "blocked": status_counts.get("blocked", 0),
        },
        "warnings": [
            *source.get("warnings", []),
            *runtime.get("warnings", []),
        ],
    }
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    validate_or_raise(
        value,
        RECONCILIATION_SCHEMA_PATH,
        "Reconciliation",
    )
    write_json(output / "reconciliation.json", value)
    return {**value, "outputDir": str(output)}


def load_discovery_graph(
    path: str | Path,
    preferred_name: str,
) -> dict[str, Any]:
    candidate = Path(path).resolve()
    if candidate.is_dir():
        candidate = candidate / preferred_name
    if not candidate.is_file():
        raise FileNotFoundError(f"证据索引不存在: {candidate}")
    value = load_json(candidate)
    if not isinstance(value, dict):
        raise ValueError(f"证据索引根节点必须是对象: {candidate}")
    return value


def _match_runtime_pages(
    route_path: str,
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = normalize_route(route_path)
    exact = [
        page
        for page in pages
        if normalize_route(str(page.get("path", "/"))) == normalized
    ]
    if exact:
        return exact
    if ":param" not in normalized and normalized != "*":
        return []
    return [
        page
        for page in pages
        if matches_route(normalized, str(page.get("path", "/")))
    ]


def _duplicate_source_paths(routes: list[dict[str, Any]]) -> set[str]:
    grouped: dict[str, set[str]] = {}
    for route in routes:
        path = normalize_route(
            str(route.get("normalized_path") or route.get("path", "/"))
        )
        component = str(route.get("component") or "")
        grouped.setdefault(path, set()).add(component)
    return {
        path
        for path, components in grouped.items()
        if len(components) > 1
    }


def _reconciliation_reasons(
    status: str,
    route_path: str,
    pages: list[dict[str, Any]],
) -> list[str]:
    if status == "matched":
        return [
            f"源码声明 {route_path}，运行时可达",
            "仅表示路由可达，不代表业务断言已通过",
        ]
    if status == "source-only":
        return [
            f"源码声明 {route_path}，但本轮运行时未到达",
            "需要补充角色、测试数据、前置导航或允许入口后重跑",
        ]
    if status == "runtime-only":
        return [
            "源码索引未覆盖该路径",
            "不能仅凭运行时页面存在就认定它是正式业务流程",
        ]
    if status == "blocked":
        return [
            "运行时因 origin 或访问限制被阻断",
            "需确认授权范围和角色凭据",
        ]
    if status == "conflict":
        if any(
            str(page.get("status", "")).startswith("http-error")
            for page in pages
        ):
            return ["源码声明存在，但运行时返回 HTTP 错误"]
        return ["同一路径存在多个不同源码组件声明，需人工确认"]
    return []


def _confidence(
    status: str,
    route: dict[str, Any],
    pages: list[dict[str, Any]],
) -> float:
    route_confidence = float(route.get("confidence", 0.5))
    if status == "matched":
        return round(min(0.98, (route_confidence + 0.9) / 2), 2)
    if status == "source-only":
        return round(route_confidence * 0.75, 2)
    if status == "runtime-only":
        return 0.45
    if status == "blocked":
        return 0.25
    if status == "conflict":
        return 0.3
    return 0.4
