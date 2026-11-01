from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import yaml

from .schema import (
    SCHEMAS_DIR,
    format_schema_errors,
    validate_instance,
)

CONTRACT_SCHEMA_PATH = SCHEMAS_DIR / "test-contract.schema.json"
TEMPLATE_PATTERN = re.compile(r"\$\{data\.([A-Za-z0-9_.-]+)\}")


class ContractError(Exception):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.name = "ContractError"
        self.details = list(details or [])


def load_contract(
    file_path: str | Path,
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    absolute_path = Path(file_path).resolve()
    source = absolute_path.read_text(encoding="utf-8")

    try:
        parsed = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise ContractError(f"测试契约 YAML 解析失败: {error}") from error

    if not isinstance(parsed, dict):
        raise ContractError("测试契约根节点必须是对象")

    errors = validate_instance(parsed, CONTRACT_SCHEMA_PATH)
    if errors:
        raise ContractError(
            "测试契约不符合 Schema",
            format_schema_errors(errors),
        )

    assert_verify_mode(parsed)
    environment = os.environ if env is None else env

    base_url_ref = parsed["target"]["baseUrlRef"]
    base_url_value = environment.get(base_url_ref)
    if not base_url_value:
        raise ContractError(f"缺少环境变量 {base_url_ref}")

    try:
        base_url = normalize_url(base_url_value)
    except ValueError as error:
        raise ContractError(
            f"环境变量 {base_url_ref} 不是合法 URL"
        ) from error

    allowed_origins: list[str] = []
    for origin in parsed["target"]["allowedOrigins"]:
        try:
            allowed_origins.append(origin_of(origin))
        except ValueError as error:
            raise ContractError(
                f"allowedOrigins 包含非法 URL: {origin}"
            ) from error

    if origin_of(base_url) not in allowed_origins:
        raise ContractError(
            f"环境变量 {base_url_ref} 的 origin 不在 allowedOrigins 中"
        )

    data, secrets = resolve_data(parsed.get("data", {}), environment)
    contract = {
        **parsed,
        "sourcePath": str(absolute_path),
        "target": {
            **parsed["target"],
            "baseUrl": base_url,
        },
        "data": data,
    }

    validate_step_data(contract)
    return contract, secrets


def assert_verify_mode(contract: Mapping[str, Any]) -> None:
    if contract.get("mode") != "verify":
        raise ContractError(
            "确定性执行器仅接受 mode: verify",
            [f"当前 mode: {contract.get('mode', 'missing')}"],
        )


def resolve_data(
    value: Any,
    env: Mapping[str, str],
) -> tuple[Any, list[str]]:
    secrets: set[str] = set()

    def visit(current: Any) -> Any:
        if isinstance(current, list):
            return [visit(item) for item in current]
        if isinstance(current, dict):
            secret_ref = current.get("secretRef")
            if isinstance(secret_ref, str):
                secret = env.get(secret_ref)
                if not secret:
                    raise ContractError(
                        f"缺少 Secret 环境变量 {secret_ref}"
                    )
                secrets.add(secret)
                return secret

            env_ref = current.get("envRef")
            if isinstance(env_ref, str):
                resolved = env.get(env_ref)
                if resolved is None:
                    raise ContractError(f"缺少环境变量 {env_ref}")
                return resolved

            return {key: visit(child) for key, child in current.items()}
        return current

    return visit(value), sorted(secrets)


def validate_step_data(contract: Mapping[str, Any]) -> None:
    unresolved: list[str] = []

    def inspect(value: Any, pointer: str) -> None:
        if isinstance(value, str):
            for match in TEMPLATE_PATTERN.finditer(value):
                key = match.group(1)
                if not has_data_path(contract.get("data", {}), key):
                    unresolved.append(f"{pointer}: data.{key}")
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                inspect(child, f"{pointer}/{index}")
            return
        if isinstance(value, dict):
            for key, child in value.items():
                inspect(child, f"{pointer}/{key}")

    inspect(contract.get("steps", []), "/steps")
    inspect(contract.get("assertions", []), "/assertions")

    if unresolved:
        raise ContractError(
            "测试契约包含未定义的数据引用",
            unresolved,
        )


def has_data_path(data: Any, path: str) -> bool:
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def resolve_template(value: Any, data: Mapping[str, Any]) -> Any:
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        current: Any = data
        for part in match.group(1).split("."):
            if not isinstance(current, dict) or part not in current:
                return ""
            current = current[part]
        return to_javascript_string(current)

    return TEMPLATE_PATTERN.sub(replace, value)


def build_target_url(base_url: str, target: str) -> str:
    return normalize_url(urljoin(base_url, target))


def normalize_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("URL 必须包含 http(s) scheme 和 host")

    path = parts.path or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc,
            path,
            parts.query,
            parts.fragment,
        )
    )


def origin_of(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("URL 必须包含 http(s) scheme 和 host")

    hostname = parts.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"

    port = parts.port
    default_port = 80 if parts.scheme.lower() == "http" else 443
    port_suffix = "" if port in {None, default_port} else f":{port}"
    return f"{parts.scheme.lower()}://{hostname}{port_suffix}"


def to_javascript_string(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    return str(value)

