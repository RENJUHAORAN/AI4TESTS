from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import random
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from .contract import (
    assert_verify_mode,
    build_target_url,
    origin_of,
    resolve_template,
    to_javascript_string,
)
from .schema import SCHEMAS_DIR, validate_or_raise

DEFAULT_TIMEOUT_MS = int(os.environ.get("UI_TEST_TIMEOUT_MS", "10000"))
MAX_CONSOLE_MESSAGES = 300
MAX_NETWORK_RECORDS = 1_000
RUN_RESULT_SCHEMA_PATH = SCHEMAS_DIR / "run-result.schema.json"


def run_contract(
    contract: dict[str, Any],
    secret_values: list[str] | None = None,
    output_root: str | Path = "artifacts/runs",
    headless: bool = True,
) -> dict[str, Any]:
    assert_verify_mode(contract)
    run_id = create_run_id(contract["id"])
    run_dir = Path(output_root).resolve() / run_id
    started_at = datetime.now(UTC)
    started_ns = time.monotonic_ns()
    step_results: list[dict[str, Any]] = []
    assertion_results: list[dict[str, Any]] = []
    console_messages: list[dict[str, str]] = []
    network_records: list[dict[str, Any]] = []
    evidence: dict[str, str] = {}
    secrets = sorted(set(filter(None, secret_values or [])))
    failure: Exception | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    trace_started = False

    run_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        try:
            launch_options: dict[str, Any] = {"headless": headless}
            executable_path = os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH")
            if executable_path:
                launch_options["executable_path"] = executable_path
            browser = playwright.chromium.launch(**launch_options)
            context = browser.new_context(**build_context_options(contract))

            if contract["evidence"]["trace"] != "never":
                context.tracing.start(
                    screenshots=True,
                    snapshots=True,
                    sources=False,
                )
                trace_started = True

            context.on(
                "page",
                lambda new_page: configure_page_events(
                    new_page,
                    console_messages,
                    network_records,
                    secrets,
                ),
            )
            page = context.new_page()
            configure_page_events(
                page,
                console_messages,
                network_records,
                secrets,
            )

            page = execute_steps(
                context,
                page,
                contract,
                secrets,
                step_results,
            )
            evaluate_assertions(
                page,
                contract,
                network_records,
                secrets,
                assertion_results,
            )
        except Exception as error:  # Playwright 与业务执行异常都在此统一分类。
            failure = error
        finally:
            ended_at = datetime.now(UTC)
            status = classify_status(failure)
            failed = status != "passed"

            if context is not None:
                try:
                    capture_evidence(
                        context=context,
                        page=page,
                        contract=contract,
                        run_dir=run_dir,
                        failed=failed,
                        console_messages=console_messages,
                        network_records=network_records,
                        secrets=secrets,
                        evidence=evidence,
                        trace_started=trace_started,
                    )
                except Exception as evidence_error:
                    evidence["captureError"] = redact(
                        str(evidence_error),
                        secrets,
                    )

            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

            result = {
                "schemaVersion": "1.0",
                "runId": run_id,
                "caseId": contract["id"],
                "mode": contract["mode"],
                "status": status,
                "startedAt": to_iso8601(started_at),
                "endedAt": to_iso8601(ended_at),
                "durationMs": elapsed_ms(started_ns),
                "steps": step_results,
                "assertions": assertion_results,
                "evidence": evidence,
                "versions": {
                    "runner": "0.2.0",
                    "python": platform.python_version(),
                    "playwright": importlib.metadata.version("playwright"),
                    "contractSha256": sha256_json(contract),
                    "environment": contract["target"]["environment"],
                },
                "reviewRequired": failed,
            }
            if failure is not None:
                result["error"] = {
                    "name": failure.__class__.__name__,
                    "message": redact(str(failure), secrets),
                    "code": getattr(failure, "code", None),
                }

            validate_or_raise(
                result,
                RUN_RESULT_SCHEMA_PATH,
                "运行结果",
            )
            write_json(run_dir / "result.json", result)
            write_json(
                run_dir / "manifest.json",
                {
                    "schemaVersion": "1.0",
                    "runId": run_id,
                    "caseId": contract["id"],
                    "status": status,
                    "caseSource": contract["sourcePath"],
                    "artifacts": list(evidence),
                    "generatedAt": to_iso8601(datetime.now(UTC)),
                },
            )

    return {**result, "runDir": str(run_dir)}


def build_context_options(contract: dict[str, Any]) -> dict[str, Any]:
    browser_config = contract.get("browser", {})
    options: dict[str, Any] = {
        "base_url": contract["target"]["baseUrl"],
        "viewport": browser_config.get(
            "viewport",
            {"width": 1440, "height": 900},
        ),
    }
    option_map = {
        "isMobile": "is_mobile",
        "deviceScaleFactor": "device_scale_factor",
        "userAgent": "user_agent",
        "locale": "locale",
        "timezoneId": "timezone_id",
        "hasTouch": "has_touch",
    }
    for contract_key, playwright_key in option_map.items():
        if contract_key in browser_config:
            options[playwright_key] = browser_config[contract_key]
    return options


def configure_page_events(
    page: Page,
    console_messages: list[dict[str, str]],
    network_records: list[dict[str, Any]],
    secrets: list[str],
) -> None:
    page.on(
        "console",
        lambda message: record_console_message(
            console_messages,
            message,
            secrets,
        ),
    )
    page.on(
        "response",
        lambda response: record_network_response(
            network_records,
            response,
            secrets,
        ),
    )


def execute_steps(
    context: BrowserContext,
    page: Page,
    contract: dict[str, Any],
    secrets: list[str],
    step_results: list[dict[str, Any]],
) -> Page:
    active_page = page
    for step in contract["steps"]:
        step_started = time.monotonic_ns()
        try:
            if step["action"] == "switchPage":
                active_page = switch_to_page(
                    context,
                    active_page,
                    step,
                    contract,
                )
                locator_used = active_page.url
            else:
                locator_used = execute_step(active_page, step, contract)
            step_results.append(
                {
                    "id": step["id"],
                    "intent": step["intent"],
                    "action": step["action"],
                    "status": "passed",
                    "locatorUsed": locator_used,
                    "durationMs": elapsed_ms(step_started),
                }
            )
        except Exception as error:
            message = redact(str(error), secrets)
            step_results.append(
                {
                    "id": step["id"],
                    "intent": step["intent"],
                    "action": step["action"],
                    "status": "failed",
                    "durationMs": elapsed_ms(step_started),
                    "error": message,
                }
            )
            raise StepExecutionError(step["id"], message) from error
    return active_page


def switch_to_page(
    context: BrowserContext,
    active_page: Page,
    step: dict[str, Any],
    contract: dict[str, Any],
) -> Page:
    expected_url = step["url"]
    timeout = step.get("timeoutMs", DEFAULT_TIMEOUT_MS)
    deadline = time.monotonic() + timeout / 1_000

    while time.monotonic() <= deadline:
        for candidate in context.pages:
            if expected_url not in candidate.url:
                continue
            assert_allowed_url(
                candidate.url,
                contract["target"]["allowedOrigins"],
            )
            candidate.wait_for_load_state(
                "domcontentloaded",
                timeout=min(timeout, 5_000),
            )
            return candidate
        # Playwright sync dispatch needs API calls, not time.sleep, to expose tab events.
        active_page.wait_for_timeout(100)

    raise TimeoutError(f"未观察到匹配的新页面: {expected_url}")


def execute_step(
    page: Page,
    step: dict[str, Any],
    contract: dict[str, Any],
) -> str:
    timeout = step.get("timeoutMs", DEFAULT_TIMEOUT_MS)

    if step["action"] == "navigate":
        target = build_target_url(
            contract["target"]["baseUrl"],
            step["url"],
        )
        assert_allowed_url(
            target,
            contract["target"]["allowedOrigins"],
        )
        page.goto(
            target,
            wait_until="domcontentloaded",
            timeout=timeout,
        )
        return target

    locator = build_locator(page, step.get("locator"))
    locator_used = describe_locator(step.get("locator", {}))
    action = step["action"]

    if action == "fill":
        locator.fill(
            to_javascript_string(
                resolve_template(step["value"], contract["data"])
            ),
            timeout=timeout,
        )
    elif action == "click":
        locator.click(timeout=timeout)
    elif action == "press":
        locator.press(
            to_javascript_string(
                resolve_template(step["value"], contract["data"])
            ),
            timeout=timeout,
        )
    elif action == "selectOption":
        locator.select_option(
            to_javascript_string(
                resolve_template(step["value"], contract["data"])
            ),
            timeout=timeout,
        )
    elif action == "check":
        locator.check(timeout=timeout)
    elif action == "uncheck":
        locator.uncheck(timeout=timeout)
    elif action == "hover":
        locator.hover(timeout=timeout)
    elif action == "waitFor":
        locator.wait_for(
            state=step.get("state", "visible"),
            timeout=timeout,
        )
    else:
        raise ValueError(f"不支持的步骤动作: {action}")

    return locator_used


def evaluate_assertions(
    page: Page,
    contract: dict[str, Any],
    network_records: list[dict[str, Any]],
    secrets: list[str],
    assertion_results: list[dict[str, Any]],
) -> None:
    for assertion in contract["assertions"]:
        assertion_started = time.monotonic_ns()
        try:
            actual = evaluate_assertion(
                page,
                assertion,
                contract,
                network_records,
            )
            assertion_results.append(
                {
                    "id": assertion["id"],
                    "type": assertion["type"],
                    "status": "passed",
                    "actual": redact_value(actual, secrets),
                    "durationMs": elapsed_ms(assertion_started),
                }
            )
        except Exception as error:
            message = redact(str(error), secrets)
            assertion_results.append(
                {
                    "id": assertion["id"],
                    "type": assertion["type"],
                    "status": "failed",
                    "durationMs": elapsed_ms(assertion_started),
                    "error": message,
                }
            )
            raise AssertionFailure(assertion["id"], message) from error


def evaluate_assertion(
    page: Page,
    assertion: dict[str, Any],
    contract: dict[str, Any],
    network_records: list[dict[str, Any]],
) -> Any:
    timeout = assertion.get("timeoutMs", DEFAULT_TIMEOUT_MS)
    expected = resolve_template(
        assertion.get("expected"),
        contract["data"],
    )
    operator = assertion.get("operator", "equals")
    assertion_type = assertion["type"]

    if assertion_type == "url":
        return poll_value(
            lambda: page.url,
            lambda value: compare(value, expected, operator, "URL"),
            timeout,
        )
    if assertion_type == "title":
        return poll_value(
            lambda: page.title(),
            lambda value: compare(value, expected, operator, "页面标题"),
            timeout,
        )
    if assertion_type == "visible":
        build_locator(page, assertion.get("locator")).wait_for(
            state="visible",
            timeout=timeout,
        )
        return True
    if assertion_type == "hidden":
        build_locator(page, assertion.get("locator")).wait_for(
            state="hidden",
            timeout=timeout,
        )
        return True
    if assertion_type == "text":
        locator = build_locator(page, assertion.get("locator"))
        locator.wait_for(state="visible", timeout=timeout)
        return poll_value(
            lambda: locator.inner_text(timeout=min(timeout, 1_000)),
            lambda value: compare(value, expected, operator, "文本"),
            timeout,
        )
    if assertion_type == "value":
        locator = build_locator(page, assertion.get("locator"))
        locator.wait_for(state="visible", timeout=timeout)
        return poll_value(
            lambda: locator.input_value(timeout=min(timeout, 1_000)),
            lambda value: compare(value, expected, operator, "输入值"),
            timeout,
        )
    if assertion_type == "network":
        matched = wait_for_network(
            network_records,
            assertion["request"],
            int(expected),
            timeout,
        )
        if matched is None:
            request = (
                f"{assertion['request'].get('method', 'ANY')} "
                f"{assertion['request'].get('path', '*')}"
            )
            raise AssertionError(
                f"未观察到匹配的网络响应: {request} -> {expected}"
            )
        return {
            "method": matched["method"],
            "path": matched["path"],
            "status": matched["status"],
        }

    raise ValueError(f"不支持的断言类型: {assertion_type}")


def poll_value(read_value: Any, check_value: Any, timeout: int) -> Any:
    deadline = time.monotonic() + timeout / 1_000
    last_error: Exception | None = None

    while time.monotonic() <= deadline:
        try:
            value = read_value()
            check_value(value)
            return value
        except Exception as error:
            last_error = error
        time.sleep(0.1)

    if last_error is not None:
        raise last_error
    raise AssertionError(f"断言在 {timeout}ms 内未满足")


def build_locator(page: Page, locator: dict[str, Any] | None) -> Any:
    if not locator:
        raise ValueError("断言或步骤缺少 locator")

    exact = locator.get("exact", True)
    if locator.get("testId"):
        result = page.get_by_test_id(locator["testId"])
    elif locator.get("role"):
        if locator.get("name"):
            result = page.get_by_role(
                locator["role"],
                name=locator["name"],
                exact=exact,
            )
        else:
            result = page.get_by_role(locator["role"])
    elif locator.get("label"):
        result = page.get_by_label(locator["label"], exact=exact)
    elif locator.get("text"):
        result = page.get_by_text(locator["text"], exact=exact)
    elif locator.get("css"):
        result = page.locator(locator["css"])
    elif locator.get("xpath"):
        result = page.locator(f"xpath={locator['xpath']}")
    else:
        raise ValueError("locator 未声明可用的定位策略")

    if "nth" in locator:
        return result.nth(locator["nth"])
    return result


def describe_locator(locator: dict[str, Any]) -> str:
    return ", ".join(
        f"{key}={to_javascript_string(value)}"
        for key, value in locator.items()
        if key not in {"exact", "nth"} and value is not None
    )


def compare(actual: Any, expected: Any, operator: str, label: str) -> None:
    actual_text = to_javascript_string(actual)
    expected_text = to_javascript_string(expected)

    if operator == "equals" and actual_text != expected_text:
        raise AssertionError(
            f"{label}不相等: expected={expected_text}, "
            f"actual={actual_text}"
        )
    if operator == "contains" and expected_text not in actual_text:
        raise AssertionError(
            f"{label}不包含目标值: expected={expected_text}, "
            f"actual={actual_text}"
        )
    if operator == "matches":
        expression = expected_text
        flags = 0
        last_slash = expected_text.rfind("/")
        if (
            expected_text.startswith("/")
            and last_slash > 0
        ):
            expression = expected_text[1:last_slash]
            suffix = expected_text[last_slash + 1:]
            if "i" in suffix:
                flags |= re.IGNORECASE
        if re.search(expression, actual_text, flags) is None:
            raise AssertionError(
                f"{label}不匹配: expected={expected_text}, "
                f"actual={actual_text}"
            )


def wait_for_network(
    records: list[dict[str, Any]],
    request: dict[str, Any],
    expected_status: int,
    timeout: int,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout / 1_000
    while time.monotonic() <= deadline:
        for record in records:
            method_matches = (
                not request.get("method")
                or record["method"].upper()
                == request["method"].upper()
            )
            path_matches = (
                not request.get("path")
                or record["path"] == request["path"]
                or record["path"].endswith(request["path"])
            )
            if (
                method_matches
                and path_matches
                and record["status"] == expected_status
            ):
                return record
        time.sleep(0.1)
    return None


def capture_evidence(
    *,
    context: BrowserContext,
    page: Page | None,
    contract: dict[str, Any],
    run_dir: Path,
    failed: bool,
    console_messages: list[dict[str, str]],
    network_records: list[dict[str, Any]],
    secrets: list[str],
    evidence: dict[str, str],
    trace_started: bool,
) -> None:
    if trace_started:
        save_trace = (
            contract["evidence"]["trace"] == "always"
            or (
                contract["evidence"]["trace"] == "on-failure"
                and failed
            )
        )
        if save_trace:
            trace_path = run_dir / "trace.zip"
            context.tracing.stop(path=str(trace_path))
            evidence["trace"] = str(trace_path)
        else:
            context.tracing.stop()

    if page is not None:
        save_screenshot = (
            contract["evidence"]["screenshot"] == "always"
            or (
                contract["evidence"]["screenshot"] == "on-failure"
                and failed
            )
        )
        if save_screenshot:
            screenshot_path = run_dir / "screenshot.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            evidence["screenshot"] = str(screenshot_path)

        snapshot_mode = contract["evidence"].get(
            "accessibilitySnapshot",
            "on-failure" if failed else "never",
        )
        save_snapshot = (
            snapshot_mode == "always"
            or (snapshot_mode == "on-failure" and failed)
        )
        if save_snapshot:
            snapshot_path = run_dir / "accessibility.txt"
            snapshot = page.locator("body").aria_snapshot()
            snapshot_path.write_text(
                redact(snapshot, secrets),
                encoding="utf-8",
            )
            evidence["accessibilitySnapshot"] = str(snapshot_path)

    if (
        contract["evidence"]["console"] == "always"
        or (
            contract["evidence"]["console"] == "on-failure"
            and failed
        )
    ):
        console_path = run_dir / "console.json"
        write_json(console_path, console_messages)
        evidence["console"] = str(console_path)

    if (
        contract["evidence"]["network"] == "always"
        or (
            contract["evidence"]["network"] == "on-failure"
            and failed
        )
    ):
        network_path = run_dir / "network.json"
        write_json(network_path, network_records)
        evidence["network"] = str(network_path)


def record_console_message(
    records: list[dict[str, str]],
    message: Any,
    secrets: list[str],
) -> None:
    if len(records) >= MAX_CONSOLE_MESSAGES:
        return
    records.append(
        {
            "type": message.type,
            "text": redact(message.text, secrets),
        }
    )


def record_network_response(
    records: list[dict[str, Any]],
    response: Any,
    secrets: list[str],
) -> None:
    if len(records) >= MAX_NETWORK_RECORDS:
        return
    try:
        parts = urlsplit(response.url)
    except ValueError:
        return
    records.append(
        {
            "method": response.request.method,
            "url": redact(
                f"{origin_of(response.url)}{parts.path}",
                secrets,
            ),
            "path": parts.path,
            "status": response.status,
            "resourceType": response.request.resource_type,
        }
    )


def assert_allowed_url(target: str, allowed_origins: list[str]) -> None:
    origin = origin_of(target)
    normalized = {origin_of(value) for value in allowed_origins}
    if origin not in normalized:
        raise ValueError(f"导航被 allowedOrigins 拦截: {origin}")


def classify_status(failure: Exception | None) -> str:
    if failure is None:
        return "passed"
    if isinstance(failure, (StepExecutionError, AssertionFailure)):
        return "failed"
    return "blocked"


def create_run_id(case_id: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"{random.SystemRandom().randrange(0, 1 << 24):06x}"
    return f"{stamp}-{case_id}-{suffix}"


def sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def redact(value: Any, secrets: list[str]) -> str:
    output = "" if value is None else str(value)
    for secret in secrets:
        output = output.replace(secret, "[REDACTED]")
    return output


def redact_value(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {
            key: redact_value(child, secrets)
            for key, child in value.items()
        }
    return value


def write_json(file_path: Path, value: Any) -> None:
    file_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def elapsed_ms(started_ns: int) -> int:
    return max(0, (time.monotonic_ns() - started_ns) // 1_000_000)


def to_iso8601(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


class StepExecutionError(Exception):
    def __init__(self, step_id: str, message: str):
        super().__init__(f"步骤 {step_id} 执行失败: {message}")
        self.name = "StepExecutionError"
        self.code = "STEP_EXECUTION_FAILED"


class AssertionFailure(Exception):
    def __init__(self, assertion_id: str, message: str):
        super().__init__(f"断言 {assertion_id} 失败: {message}")
        self.name = "AssertionFailure"
        self.code = "ASSERTION_FAILED"

