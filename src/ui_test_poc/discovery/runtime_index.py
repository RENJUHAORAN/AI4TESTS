from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import yaml

from ..schema import validate_or_raise
from .models import (
    SCHEMA_VERSION,
    RuntimeApiCall,
    RuntimeGraph,
    RuntimePage,
    RuntimeTransition,
    load_json,
    new_run_id,
    normalize_route,
    origin_from_url,
    path_from_url,
    sanitize_url,
    stable_id,
    utc_now,
    write_json,
    write_jsonl,
)
from .schema import (
    DISCOVERY_CONFIG_SCHEMA_PATH,
    RUNTIME_GRAPH_SCHEMA_PATH,
)

DEFAULT_ALLOWED_METHODS = {"GET", "HEAD", "OPTIONS"}
MUTATION_WORDS = re.compile(
    r"(create|update|delete|remove|submit|order|pay|refund|approve|"
    r"authorize|permission|grant|revoke|transfer|checkout)",
    re.IGNORECASE,
)
QUERY_WORDS = re.compile(
    r"(search|query|list|detail|page|filter|lookup)",
    re.IGNORECASE,
)


def load_runtime_config(
    config_path: str | Path,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(config_path).resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("运行时探索配置根节点必须是 YAML 对象")
    return normalize_runtime_config(data, overrides)


def normalize_runtime_config(
    config: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("运行时探索配置根节点必须是 YAML 对象")
    merged = _deep_merge(config, overrides or {})
    if (merged.get("safety") or {}).get("allowMutations"):
        raise ValueError(
            "流程探索禁止开启 allowMutations；写操作必须交由独立 Contract 审批执行"
        )
    validate_or_raise(
        merged,
        DISCOVERY_CONFIG_SCHEMA_PATH,
        "发现配置",
    )
    target = merged.setdefault("target", {})
    env_name = target.get("baseUrlRef")
    if env_name and not target.get("baseUrl"):
        target["baseUrl"] = os.environ.get(str(env_name))
    if not target.get("baseUrl"):
        raise ValueError("运行时探索配置缺少 target.baseUrl 或可解析的 baseUrlRef")
    target["baseUrl"] = str(target["baseUrl"]).rstrip("/") + "/"
    if not target.get("allowedOrigins"):
        target["allowedOrigins"] = [origin_from_url(target["baseUrl"])]
    return merged


def explore_runtime(
    config: dict[str, Any],
    output_dir: str | Path,
    *,
    source_graph_path: str | Path | None = None,
    headless: bool = True,
) -> dict[str, Any]:
    config = normalize_runtime_config(config)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as error:
        raise RuntimeError(f"Playwright 不可用: {error}") from error

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = new_run_id("runtime")
    generated_at = utc_now()
    target = dict(config["target"])
    safety = {
        "maxPages": 80,
        "maxDepth": 4,
        "maxLinksPerPage": 120,
        "includeSourceRoutes": True,
        "allowQueryNavigation": True,
        "allowMutations": False,
        "waitAfterLoadMs": 300,
        **config.get("safety", {}),
    }
    if safety["allowMutations"]:
        raise ValueError(
            "流程探索禁止开启 allowMutations；写操作必须交由独立 Contract 审批执行"
        )

    roles = _normalize_roles(config.get("roles"))
    source_candidates = _load_source_candidates(
        source_graph_path,
        target["baseUrl"],
        target["allowedOrigins"],
    )
    browser_config = config.get("browser", {})
    timeout_ms = int(config.get("timeoutMs", 20_000))
    pages: list[RuntimePage] = []
    transitions: list[RuntimeTransition] = []
    api_calls: list[RuntimeApiCall] = []
    warnings: list[str] = []

    try:
        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {"headless": headless}
            executable_path = os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH")
            if executable_path:
                launch_options["executable_path"] = executable_path
            browser = playwright.chromium.launch(**launch_options)
            try:
                for role in roles:
                    role_pages, role_transitions, role_calls, role_warnings = (
                        _explore_role(
                            browser,
                            role,
                            target,
                            safety,
                            browser_config,
                            source_candidates,
                            output,
                            run_id,
                            timeout_ms,
                        )
                    )
                    pages.extend(role_pages)
                    transitions.extend(role_transitions)
                    api_calls.extend(role_calls)
                    warnings.extend(role_warnings)
            finally:
                browser.close()
        status = "observed-runtime" if pages else "blocked"
    except Exception as error:
        warnings.append(f"运行时探索失败: {error}")
        status = "blocked"

    graph = RuntimeGraph(
        schemaVersion=SCHEMA_VERSION,
        runId=run_id,
        generatedAt=generated_at,
        status=status,
        target=target,
        roles=roles,
        pages=pages,
        transitions=_deduplicate_transitions(transitions),
        apiCalls=_deduplicate_api_calls(api_calls),
        warnings=warnings,
        stats={
            "roles": len(roles),
            "pages": len(pages),
            "transitions": len(_deduplicate_transitions(transitions)),
            "apiCalls": len(_deduplicate_api_calls(api_calls)),
            "warnings": len(warnings),
        },
    )
    value = graph.as_dict()
    validate_or_raise(
        value,
        RUNTIME_GRAPH_SCHEMA_PATH,
        "Runtime Graph",
    )
    write_json(output / "runtime-graph.json", value)
    write_jsonl(output / "pages.jsonl", [asdict(item) for item in pages])
    write_jsonl(
        output / "transitions.jsonl",
        [asdict(item) for item in graph.transitions],
    )
    write_jsonl(
        output / "api-calls.jsonl",
        [asdict(item) for item in graph.apiCalls],
    )
    return {**value, "outputDir": str(output)}


def _explore_role(
    browser: Any,
    role: dict[str, Any],
    target: dict[str, Any],
    safety: dict[str, Any],
    browser_config: dict[str, Any],
    source_candidates: list[str],
    output: Path,
    run_id: str,
    timeout_ms: int,
) -> tuple[
    list[RuntimePage],
    list[RuntimeTransition],
    list[RuntimeApiCall],
    list[str],
]:
    role_name = str(role["name"])
    context_options: dict[str, Any] = {
        "viewport": browser_config.get(
            "viewport",
            {"width": 1440, "height": 900},
        )
    }
    browser_option_map = {
        "isMobile": "is_mobile",
        "deviceScaleFactor": "device_scale_factor",
        "userAgent": "user_agent",
        "locale": "locale",
        "timezoneId": "timezone_id",
        "hasTouch": "has_touch",
    }
    for source_key, playwright_key in browser_option_map.items():
        if source_key in browser_config:
            context_options[playwright_key] = browser_config[source_key]
    storage_ref = role.get("storageStateRef")
    storage_path = role.get("storageState") or (
        os.environ.get(str(storage_ref)) if storage_ref else None
    )
    if storage_path:
        context_options["storage_state"] = storage_path
    context = browser.new_context(**context_options)
    page = context.new_page()
    current_path = "/"
    role_calls: list[RuntimeApiCall] = []
    blocked_requests: list[str] = []
    console_errors = [0]
    page.route(
        "**/*",
        lambda route: _guard_request(
            route,
            role_calls,
            blocked_requests,
            role_name,
            current_path,
        ),
    )
    page.on(
        "console",
        lambda message: _record_console_error(console_errors, message),
    )
    page.on(
        "response",
        lambda response: _record_response(
            role_calls,
            response,
            role_name,
            current_path,
        ),
    )

    max_pages = int(role.get("maxPages", safety["maxPages"]))
    max_depth = int(role.get("maxDepth", safety["maxDepth"]))
    wait_after_load_ms = int(safety["waitAfterLoadMs"])
    start_paths = list(role.get("startPaths") or ["/"])
    if safety["includeSourceRoutes"] and role.get("includeSourceRoutes", True):
        start_paths.extend(source_candidates)
    start_paths = _deduplicate_paths(start_paths)

    queue: deque[tuple[str, str | None, int, str]] = deque(
        (path, None, 0, "seed") for path in start_paths
    )
    queued_paths = set(start_paths)
    visited: set[str] = set()
    pages: list[RuntimePage] = []
    transitions: list[RuntimeTransition] = []
    warnings: list[str] = []
    snapshot_dir = output / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    while queue and len(pages) < max_pages:
        requested_path, from_path, depth, action = queue.popleft()
        if requested_path in visited:
            continue
        url = _build_url(target["baseUrl"], requested_path)
        if not _is_allowed_url(url, target["allowedOrigins"]):
            warnings.append(f"跳过 origin 白名单外地址: {sanitize_url(url)}")
            continue
        visited.add(requested_path)
        observed_at = utc_now()
        http_status: int | None = None
        status = "observed"
        current_path = normalize_route(requested_path)
        snapshot_path: str | None = None

        console_errors[0] = 0
        blocked_requests.clear()
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            http_status = response.status if response else None
            page.wait_for_load_state("networkidle", timeout=2_000)
        except Exception:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=2_000)
            except Exception:
                pass
        if wait_after_load_ms > 0:
            page.wait_for_timeout(wait_after_load_ms)

        final_url = page.url
        final_path = path_from_url(final_url)
        current_path = final_path
        title = _safe_text(page.title())
        if int(http_status or 0) >= 400:
            status = "http-error"
        if not _is_allowed_url(final_url, target["allowedOrigins"]):
            status = "blocked-origin"
            warnings.append(
                f"{role_name} 访问被重定向到白名单外 origin: "
                f"{sanitize_url(final_url)}"
            )
        if console_errors[0]:
            status = "observed-with-errors" if status == "observed" else status
        if blocked_requests:
            warnings.append(
                f"{role_name} 在 {final_path} 阻止了以下非只读请求: "
                f"{', '.join(blocked_requests)}"
            )

        index = len(pages) + 1
        try:
            snapshot = page.locator("body").aria_snapshot(timeout=3_000)
            snapshot_relative = (
                f"snapshots/{_safe_name(role_name)}-{index:04d}.yml"
            )
            (output / snapshot_relative).write_text(
                snapshot,
                encoding="utf-8",
            )
            snapshot_path = snapshot_relative
        except Exception:
            pass

        page_record = RuntimePage(
            id=stable_id("RUN-PAGE", run_id, role_name, final_path, depth),
            role=role_name,
            requestedUrl=sanitize_url(url),
            finalUrl=sanitize_url(final_url),
            path=final_path,
            title=title,
            status=status,
            httpStatus=http_status,
            depth=depth,
            observedAt=observed_at,
            snapshotPath=snapshot_path,
            consoleErrorCount=console_errors[0],
        )
        pages.append(page_record)
        if from_path and from_path != final_path:
            transitions.append(
                RuntimeTransition(
                    id=stable_id(
                        "RUN-TRANSITION",
                        role_name,
                        from_path,
                        final_path,
                        action,
                    ),
                    role=role_name,
                    fromPath=normalize_route(from_path),
                    toPath=final_path,
                    action=action,
                    depth=depth,
                    observedAt=observed_at,
                )
            )

        if depth >= max_depth:
            continue
        links = _extract_internal_links(
            page,
            target["allowedOrigins"],
            int(safety["maxLinksPerPage"]),
        )
        for link in links:
            if link in visited or link in queued_paths:
                continue
            if not _query_navigation_allowed(
                link,
                bool(safety["allowQueryNavigation"]),
            ):
                warnings.append(f"跳过查询型导航: {sanitize_url(link)}")
                continue
            queued_paths.add(link)
            queue.append((link, final_path, depth + 1, "link"))

    context.close()
    if len(pages) >= max_pages and queue:
        warnings.append(
            f"角色 {role_name} 达到 maxPages={max_pages}，仍有未探索页面。"
        )
    return pages, transitions, role_calls, warnings
def _record_console_error(counter: list[int], message: Any) -> None:
    if getattr(message, "type", "") == "error":
        counter[0] += 1


def _guard_request(
    route: Any,
    records: list[RuntimeApiCall],
    blocked_requests: list[str],
    role_name: str,
    current_path: str,
) -> None:
    try:
        request = route.request
        method = request.method.upper()
        if method in DEFAULT_ALLOWED_METHODS:
            route.continue_()
            return

        url = sanitize_url(request.url)
        records.append(
            RuntimeApiCall(
                id=stable_id("RUN-API", role_name, current_path, method, url),
                role=role_name,
                pagePath=normalize_route(current_path),
                method=method,
                url=url,
                status=None,
                resourceType=getattr(request, "resource_type", "request"),
                classification="mutation",
                observedAt=utc_now(),
            )
        )
        blocked_requests.append(f"{method} {url}")
        route.abort()
    except Exception:
        try:
            route.abort()
        except Exception:
            pass


def _record_response(
    records: list[RuntimeApiCall],
    response: Any,
    role_name: str,
    current_path: str,
) -> None:
    try:
        request = response.request
        resource_type = getattr(request, "resource_type", "")
        if resource_type not in {"xhr", "fetch"}:
            return
        url = response.url
        method = request.method.upper()
        records.append(
            RuntimeApiCall(
                id=stable_id("RUN-API", role_name, current_path, method, url),
                role=role_name,
                pagePath=normalize_route(current_path),
                method=method,
                url=sanitize_url(url),
                status=response.status,
                resourceType=resource_type,
                classification=_classify_api(method, url),
                observedAt=utc_now(),
            )
        )
    except Exception:
        return


def _classify_api(method: str, url: str) -> str:
    if method.upper() not in DEFAULT_ALLOWED_METHODS:
        return "mutation"
    path = urlsplit(url).path
    if MUTATION_WORDS.search(path):
        return "potential-mutation"
    if QUERY_WORDS.search(path):
        return "read-query"
    return "read"


def _extract_internal_links(
    page: Any,
    allowed_origins: list[str],
    maximum: int,
) -> list[str]:
    links: list[str] = []
    try:
        anchors = page.locator("a[href]").all()
    except Exception:
        return links
    for anchor in anchors:
        if len(links) >= maximum:
            break
        try:
            href = anchor.get_attribute("href")
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            absolute = urljoin(page.url, href)
            if not _is_allowed_url(absolute, allowed_origins):
                continue
            parsed = urlsplit(absolute)
            path = normalize_route(parsed.path)
            if parsed.query:
                path = f"{path}?{parsed.query}"
            if path not in links:
                links.append(path)
        except Exception:
            continue
    return links


def _query_navigation_allowed(path: str, enabled: bool) -> bool:
    return enabled or "?" not in path


def _build_url(base_url: str, path: str) -> str:
    if "://" in path:
        return path
    return urljoin(base_url, path.lstrip("/"))


def _is_allowed_url(url: str, allowed_origins: list[str]) -> bool:
    return origin_from_url(url) in {
        origin.rstrip("/") for origin in allowed_origins
    }


def _load_source_candidates(
    source_graph_path: str | Path | None,
    base_url: str,
    allowed_origins: list[str],
) -> list[str]:
    if not source_graph_path:
        return []
    path = Path(source_graph_path)
    if path.is_dir():
        path = path / "source-graph.json"
    if not path.is_file():
        return []
    graph = load_json(path)
    candidates: list[str] = []
    for route in graph.get("routes", []):
        route_path = str(route.get("path", ""))
        if ":param" in normalize_route(route_path) or route_path in {"*", "**"}:
            continue
        candidates.append(route_path)
    return candidates


def _normalize_roles(value: Any) -> list[dict[str, Any]]:
    if not value:
        return [{"name": "anonymous", "startPaths": ["/"]}]
    roles: list[dict[str, Any]] = []
    for index, role in enumerate(value):
        if isinstance(role, str):
            role = {"name": role}
        normalized = dict(role)
        normalized.setdefault("name", f"role-{index + 1}")
        normalized.setdefault("startPaths", ["/"])
        roles.append(normalized)
    names = [role["name"] for role in roles]
    if len(names) != len(set(names)):
        raise ValueError("roles.name 必须唯一")
    return roles


def _deduplicate_paths(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        path = value if "?" in value else normalize_route(value)
        if path not in result:
            result.append(path)
    return result


def _deduplicate_transitions(
    values: list[RuntimeTransition],
) -> list[RuntimeTransition]:
    unique: dict[tuple[str, str, str], RuntimeTransition] = {}
    for value in values:
        unique[(value.role, value.fromPath, value.toPath)] = value
    return sorted(
        unique.values(),
        key=lambda item: (item.role, item.fromPath, item.toPath),
    )


def _deduplicate_api_calls(
    values: list[RuntimeApiCall],
) -> list[RuntimeApiCall]:
    unique: dict[tuple[str, str, str, str], RuntimeApiCall] = {}
    for value in values:
        unique[(value.role, value.pagePath, value.method, value.url)] = value
    return sorted(
        unique.values(),
        key=lambda item: (item.role, item.pagePath, item.method, item.url),
    )


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "role"


def _safe_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:300]


def _deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if (
            isinstance(value, dict)
            and isinstance(result.get(key), dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
