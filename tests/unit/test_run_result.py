from pathlib import Path

from ui_test_poc.schema import (
    format_schema_errors,
    validate_instance,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/run-result.schema.json"


def create_result():
    return {
        "schemaVersion": "1.0",
        "runId": "20261101T000000Z-LOGIN-001-abc123",
        "caseId": "LOGIN-001",
        "mode": "verify",
        "status": "passed",
        "startedAt": "2026-11-01T00:00:00.000Z",
        "endedAt": "2026-11-01T00:00:01.000Z",
        "durationMs": 1000,
        "steps": [
            {
                "id": "open-login",
                "intent": "打开登录页",
                "action": "navigate",
                "status": "passed",
                "locatorUsed": "http://127.0.0.1:4173/login",
                "durationMs": 500,
            }
        ],
        "assertions": [
            {
                "id": "login-url",
                "type": "url",
                "status": "passed",
                "actual": "http://127.0.0.1:4173/login",
                "durationMs": 100,
            }
        ],
        "evidence": {
            "trace": "artifacts/runs/run/trace.zip",
        },
        "versions": {
            "runner": "0.2.0",
            "python": "3.14.5",
            "playwright": "1.64.1",
            "contractSha256": "a" * 64,
            "environment": "local-demo",
        },
        "reviewRequired": False,
    }


def test_run_result_matches_schema():
    errors = validate_instance(create_result(), SCHEMA_PATH)
    assert not errors, "\n".join(format_schema_errors(errors))


def test_run_result_rejects_undeclared_fields():
    result = create_result()
    result["reviewedByModel"] = True

    errors = validate_instance(result, SCHEMA_PATH)
    messages = "\n".join(format_schema_errors(errors))
    assert messages
    assert "additional properties" in messages.lower()

