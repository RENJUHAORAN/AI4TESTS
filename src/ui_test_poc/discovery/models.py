from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMA_VERSION = "1.0"
DYNAMIC_SEGMENT_PATTERN = re.compile(
    r"(?<=/)(?::[A-Za-z_][\w-]*|\{[A-Za-z_][\w-]*\}"
    r"|\[[A-Za-z_][\w-]*\]|<[A-Za-z_][\w-]*>)"
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )


def new_run_id(prefix: str = "discovery") -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{prefix}-{secrets.token_hex(3)}"


def stable_id(prefix: str, *parts: object, length: int = 10) -> str:
    digest = hashlib.sha256(
        "\x1f".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:length].upper()}"


def normalize_route(value: str) -> str:
    path = urlsplit(value).path if "://" in value else value.split("?", 1)[0]
    path = path.split("#", 1)[0].strip()
    if not path:
        return "/"
    path = re.sub(r"/{2,}", "/", path)
    path = DYNAMIC_SEGMENT_PATTERN.sub(":param", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def route_regex(route: str) -> re.Pattern[str]:
    normalized = normalize_route(route)
    if normalized == "*":
        return re.compile(r"^.*$")
    pieces: list[str] = []
    for segment in normalized.strip("/").split("/"):
        if not segment:
            continue
        pieces.append(r"[^/]+" if segment == ":param" else re.escape(segment))
    body = "/".join(pieces)
    return re.compile(rf"^/{body}$" if body else r"^/$")


def matches_route(template: str, actual: str) -> bool:
    return bool(route_regex(template).match(normalize_route(actual)))


def sanitize_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "[invalid-url]"
    if not parsed.scheme or not parsed.netloc:
        return normalize_route(value)
    query = [
        (key, "[REDACTED]")
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            normalize_route(parsed.path),
            urlencode(query),
            "",
        )
    )


def path_from_url(value: str) -> str:
    try:
        return normalize_route(urlsplit(value).path)
    except ValueError:
        return normalize_route(value)


def origin_from_url(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}"


def write_json(path: str | Path, value: Any) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def write_jsonl(path: str | Path, values: list[Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(value, ensure_ascii=False) + "\n"
        for value in values
    )
    output.write_text(text, encoding="utf-8")
    return output


def to_relative(value: str | Path, root: str | Path) -> str:
    try:
        return Path(value).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(value).resolve().as_posix()


@dataclass(slots=True)
class SourceRef:
    path: str
    line: int
    symbol: str | None = None


@dataclass(slots=True)
class SourceRoute:
    id: str
    path: str
    normalized_path: str
    name: str
    component: str | None
    source: SourceRef
    kind: str
    confidence: float


@dataclass(slots=True)
class SourceLink:
    id: str
    target: str
    normalized_target: str
    action: str
    source: SourceRef
    confidence: float


@dataclass(slots=True)
class SourceGraph:
    schemaVersion: str
    runId: str
    generatedAt: str
    repository: str
    status: str
    routes: list[SourceRoute] = field(default_factory=list)
    links: list[SourceLink] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimePage:
    id: str
    role: str
    requestedUrl: str
    finalUrl: str
    path: str
    title: str
    status: str
    httpStatus: int | None
    depth: int
    observedAt: str
    snapshotPath: str | None
    consoleErrorCount: int


@dataclass(slots=True)
class RuntimeTransition:
    id: str
    role: str
    fromPath: str
    toPath: str
    action: str
    depth: int
    observedAt: str


@dataclass(slots=True)
class RuntimeApiCall:
    id: str
    role: str
    pagePath: str
    method: str
    url: str
    status: int | None
    resourceType: str
    classification: str
    observedAt: str


@dataclass(slots=True)
class RuntimeGraph:
    schemaVersion: str
    runId: str
    generatedAt: str
    status: str
    target: dict[str, Any]
    roles: list[dict[str, Any]]
    pages: list[RuntimePage] = field(default_factory=list)
    transitions: list[RuntimeTransition] = field(default_factory=list)
    apiCalls: list[RuntimeApiCall] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def object_from_dict(cls: type[Any], value: dict[str, Any]) -> Any:
    return cls(**value)
