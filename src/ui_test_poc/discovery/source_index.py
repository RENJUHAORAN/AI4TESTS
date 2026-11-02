from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..schema import validate_or_raise
from .models import (
    SCHEMA_VERSION,
    SourceGraph,
    SourceLink,
    SourceRef,
    SourceRoute,
    new_run_id,
    normalize_route,
    stable_id,
    to_relative,
    utc_now,
    write_json,
)
from .schema import SOURCE_GRAPH_SCHEMA_PATH

SOURCE_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue"}
ROUTER_FILE_PATTERN = re.compile(
    r"(router|routes?|route-config|navigation|sidebar|menu)",
    re.IGNORECASE,
)
EXCLUDED_PARTS = {
    ".git",
    ".next",
    ".nuxt",
    "artifacts",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "vendor",
}
PATH_PROPERTY_PATTERN = re.compile(
    r"\bpath\s*:\s*['\"`](?P<path>[^'\"`]*)['\"`]"
)
ROUTE_JSX_PATTERN = re.compile(r"<Route\b(?P<attrs>[^>]*)>", re.DOTALL)
JSX_PATH_PATTERN = re.compile(r"\bpath\s*=\s*\{?\s*['\"`]([^'\"`]+)")
OBJECT_NAME_PATTERN = re.compile(
    r"\bname\s*:\s*['\"`](?P<name>[^'\"`]+)['\"`]"
)
OBJECT_COMPONENT_PATTERN = re.compile(
    r"\bcomponent\s*:\s*(?P<component>[A-Za-z_$][\w$]*)"
)
ELEMENT_COMPONENT_PATTERN = re.compile(
    r"\belement\s*:\s*<\s*(?P<component>[A-Za-z_$][\w$]*)"
)
JSX_ELEMENT_COMPONENT_PATTERN = re.compile(
    r"\belement\s*=\s*\{\s*<\s*(?P<component>[A-Za-z_$][\w$]*)"
)
COMPONENT_PROP_PATTERN = re.compile(
    r"\bcomponent\s*=\s*\{\s*(?P<component>[A-Za-z_$][\w$]*)"
)
LAZY_IMPORT_PATTERN = re.compile(
    r"(?:import|require)\s*\(\s*['\"`](?P<module>\.[^'\"`]+)['\"`]\s*\)"
)
LINK_PATTERNS = (
    (
        "link",
        re.compile(
            r"<(?:Link|NavLink|RouterLink)\b[^>]*\bto\s*="
            r"\s*\{?\s*['\"`](?P<target>/[^'\"`]*)['\"`]",
            re.IGNORECASE,
        ),
    ),
    (
        "navigate",
        re.compile(
            r"\b(?:navigate|push|replace|redirect)\s*\(\s*"
            r"['\"`](?P<target>/[^'\"`]*)['\"`]"
        ),
    ),
    (
        "location",
        re.compile(
            r"\b(?:location\.href|location\.assign)\s*=\s*"
            r"['\"`](?P<target>/[^'\"`]*)['\"`]"
        ),
    ),
)


def build_source_graph(
    repository: str | Path,
    output_dir: str | Path,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    repo = Path(repository).resolve()
    output = Path(output_dir).resolve()
    if not repo.is_dir():
        raise FileNotFoundError(f"前端源码目录不存在: {repo}")

    output.mkdir(parents=True, exist_ok=True)
    run_id = new_run_id("source")
    routes: list[SourceRoute] = []
    links: list[SourceLink] = []
    warnings: list[str] = []
    files = list(_iter_source_files(repo, include, exclude))

    for file_path in files:
        relative = file_path.relative_to(repo).as_posix()
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            warnings.append(f"跳过非 UTF-8 文件: {relative}")
            continue
        except OSError as error:
            warnings.append(f"无法读取 {relative}: {error}")
            continue

        extracted = _extract_config_routes(relative, source)
        extracted.extend(_extract_file_convention_routes(relative))
        routes.extend(extracted)
        links.extend(_extract_links(relative, source))

    routes, duplicates = _deduplicate_routes(routes)
    for duplicate in duplicates:
        warnings.append(
            "同一路径被多次声明，需人工确认路由优先级: "
            f"{duplicate}"
        )
    if not routes:
        warnings.append(
            "未发现静态路由声明。请检查源码目录、路由写法或使用运行时探索补齐。"
        )
    if not files:
        warnings.append("源码目录中没有发现可分析的 JavaScript/TypeScript 文件。")

    graph = SourceGraph(
        schemaVersion=SCHEMA_VERSION,
        runId=run_id,
        generatedAt=utc_now(),
        repository=str(repo),
        status="observed-source" if routes else "review-required",
        routes=routes,
        links=links,
        warnings=warnings,
        stats={
            "filesScanned": len(files),
            "routes": len(routes),
            "links": len(links),
            "warnings": len(warnings),
        },
    )
    value = graph.as_dict()
    validate_or_raise(
        value,
        SOURCE_GRAPH_SCHEMA_PATH,
        "Source Graph",
    )
    write_json(output / "source-graph.json", value)
    write_json(
        output / "routes.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "generatedAt": graph.generatedAt,
            "repository": str(repo),
            "routes": [asdict(route) for route in routes],
            "warnings": warnings,
        },
    )
    write_json(
        output / "links.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "runId": run_id,
            "links": [asdict(link) for link in links],
        },
    )
    return {**value, "outputDir": str(output)}


def _iter_source_files(
    repo: Path,
    include: list[str] | None,
    exclude: list[str] | None,
) -> list[Path]:
    include_patterns = [re.compile(pattern) for pattern in include or []]
    exclude_patterns = [re.compile(pattern) for pattern in exclude or []]
    selected: list[Path] = []
    for path in repo.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        if any(part in EXCLUDED_PARTS for part in path.relative_to(repo).parts):
            continue
        relative = path.relative_to(repo).as_posix()
        if include_patterns and not any(
            pattern.search(relative) for pattern in include_patterns
        ):
            continue
        if any(pattern.search(relative) for pattern in exclude_patterns):
            continue
        selected.append(path)
    return sorted(selected)


def _extract_config_routes(
    relative: str,
    source: str,
) -> list[SourceRoute]:
    routes: list[SourceRoute] = []
    router_hint = bool(ROUTER_FILE_PATTERN.search(relative))

    for match in PATH_PROPERTY_PATTERN.finditer(source):
        path = match.group("path").strip()
        if not _looks_like_route_path(path, router_hint):
            continue
        context = source[match.start() : match.start() + 900]
        name_match = OBJECT_NAME_PATTERN.search(context)
        component_match = (
            OBJECT_COMPONENT_PATTERN.search(context)
            or ELEMENT_COMPONENT_PATTERN.search(context)
            or LAZY_IMPORT_PATTERN.search(context)
        )
        component = component_match.group(
            "component" if "component" in component_match.groupdict() else "module"
        ) if component_match else None
        routes.append(
            _source_route(
                relative,
                source,
                match.start(),
                path,
                name_match.group("name") if name_match else _title_from_path(path),
                component,
                "route-object",
                0.72 if router_hint else 0.58,
            )
        )

    for match in ROUTE_JSX_PATTERN.finditer(source):
        attrs = match.group("attrs")
        path_match = JSX_PATH_PATTERN.search(attrs)
        if not path_match:
            continue
        path = path_match.group(1).strip()
        component_match = (
            JSX_ELEMENT_COMPONENT_PATTERN.search(attrs)
            or COMPONENT_PROP_PATTERN.search(attrs)
        )
        routes.append(
            _source_route(
                relative,
                source,
                match.start(),
                path,
                _title_from_path(path),
                component_match.group("component") if component_match else None,
                "route-jsx",
                0.82,
            )
        )
    return routes


def _extract_file_convention_routes(relative: str) -> list[SourceRoute]:
    parts = Path(relative).parts
    if "node_modules" in parts:
        return []
    stem = Path(relative).stem
    route_path: str | None = None
    component = stem

    lowered = [part.lower() for part in parts]
    if stem.lower() in {"page", "route", "index"}:
        if "app" in lowered:
            app_index = max(i for i, part in enumerate(lowered) if part == "app")
            segments = list(parts[app_index + 1 : -1])
        else:
            return []
    elif "pages" in lowered or "views" in lowered:
        root_name = "pages" if "pages" in lowered else "views"
        root_index = max(i for i, part in enumerate(lowered) if part == root_name)
        segments = list(parts[root_index + 1 :])
        segments[-1] = Path(segments[-1]).stem
        if segments[-1] == "index":
            segments.pop()
    else:
        return []

    segments = [
        re.sub(r"^\[(.+)\]$", r":\1", segment)
        for segment in segments
        if not segment.startswith("(") and segment not in {"_app", "_document"}
    ]
    if any(segment.lower() in {"api", "404", "500"} for segment in segments):
        return []
    route_path = "/" + "/".join(segments) if segments else "/"
    line = 1
    return [
        SourceRoute(
            id=stable_id("SRC-ROUTE", route_path, relative),
            path=route_path,
            normalized_path=normalize_route(route_path),
            name=_title_from_path(route_path),
            component=component,
            source=SourceRef(relative, line, component),
            kind="file-convention",
            confidence=0.7,
        )
    ]


def _extract_links(relative: str, source: str) -> list[SourceLink]:
    links: list[SourceLink] = []
    seen: set[tuple[str, int, str]] = set()
    for action, pattern in LINK_PATTERNS:
        for match in pattern.finditer(source):
            target = match.group("target").strip()
            line = _line_number(source, match.start())
            key = (target, line, action)
            if key in seen:
                continue
            seen.add(key)
            links.append(
                SourceLink(
                    id=stable_id("SRC-LINK", relative, line, target, action),
                    target=target,
                    normalized_target=normalize_route(target),
                    action=action,
                    source=SourceRef(relative, line),
                    confidence=0.66,
                )
            )
    return links


def _source_route(
    relative: str,
    source: str,
    offset: int,
    path: str,
    name: str,
    component: str | None,
    kind: str,
    confidence: float,
) -> SourceRoute:
    line = _line_number(source, offset)
    normalized = normalize_route(path)
    return SourceRoute(
        id=stable_id("SRC-ROUTE", relative, line, normalized),
        path=path or "/",
        normalized_path=normalized,
        name=name,
        component=component,
        source=SourceRef(relative, line, component),
        kind=kind,
        confidence=confidence,
    )


def _deduplicate_routes(
    routes: list[SourceRoute],
) -> tuple[list[SourceRoute], list[str]]:
    unique: dict[tuple[str, int, str], SourceRoute] = {}
    for route in routes:
        key = (
            route.source.path,
            route.source.line,
            route.normalized_path,
        )
        unique[key] = route
    result = sorted(
        unique.values(),
        key=lambda item: (
            item.normalized_path,
            item.source.path,
            item.source.line,
        ),
    )
    by_path: dict[str, list[SourceRoute]] = {}
    for route in result:
        by_path.setdefault(route.normalized_path, []).append(route)
    duplicates = [
        f"{path} ({len(items)} 个声明)"
        for path, items in by_path.items()
        if len(items) > 1
    ]
    return result, duplicates


def _looks_like_route_path(path: str, router_hint: bool) -> bool:
    if path in {"", "*", "**"}:
        return router_hint
    if path.startswith("/"):
        return True
    return router_hint and bool(re.fullmatch(r"[A-Za-z0-9_:\-./\[\]]+", path))


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _title_from_path(path: str) -> str:
    value = normalize_route(path).strip("/")
    if not value:
        return "首页"
    return value.replace(":", "").replace("-", " ").replace("_", " ").title()
