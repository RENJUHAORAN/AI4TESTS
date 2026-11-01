from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "schemas"

_validator_cache: dict[Path, Draft202012Validator] = {}


class SchemaValidationError(Exception):
    def __init__(self, label: str, details: Iterable[str] | None = None):
        super().__init__(f"{label} 不符合 JSON Schema")
        self.name = "SchemaValidationError"
        self.code = "RESULT_SCHEMA_INVALID"
        self.details = list(details or [])


def load_schema(schema_path: str | Path) -> dict[str, Any]:
    path = Path(schema_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_schema_validator(schema_path: str | Path) -> Draft202012Validator:
    path = Path(schema_path).resolve()
    if path not in _validator_cache:
        _validator_cache[path] = Draft202012Validator(load_schema(path))
    return _validator_cache[path]


def validate_instance(
    value: Mapping[str, Any],
    schema_path: str | Path,
) -> list[ValidationError]:
    validator = get_schema_validator(schema_path)
    return sorted(
        validator.iter_errors(value),
        key=lambda error: (list(error.absolute_path), error.message),
    )


def format_schema_errors(
    errors: Iterable[ValidationError],
) -> list[str]:
    return [
        f"{format_path(error.absolute_path)} {error.message}"
        for error in errors
    ]


def validate_or_raise(
    value: Mapping[str, Any],
    schema_path: str | Path,
    label: str,
) -> None:
    errors = validate_instance(value, schema_path)
    if errors:
        raise SchemaValidationError(label, format_schema_errors(errors))


def format_path(path: Iterable[str | int]) -> str:
    parts = list(path)
    if not parts:
        return "/"
    encoded = [
        str(part).replace("~", "~0").replace("/", "~1")
        for part in parts
    ]
    return "/" + "/".join(encoded)

