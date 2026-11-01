from pathlib import Path

from ui_test_poc.schema import (
    format_schema_errors,
    validate_instance,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/codex-run-result.schema.json"


def create_observed_result():
    return {
        "runId": "run-20261101-001",
        "caseId": "LOGIN-001",
        "mode": "explore",
        "observedStatus": "observed-pass",
        "authoritativeStatus": None,
        "startedAt": "2026-11-01T10:00:00+08:00",
        "endedAt": "2026-11-01T10:00:03+08:00",
        "steps": [
            {
                "id": "open-login",
                "intent": "打开登录页",
                "action": "browser_navigate",
                "status": "observed-pass",
                "locatorUsed": None,
                "durationMs": 820,
                "error": None,
            }
        ],
        "assertions": [],
        "evidence": {
            "trace": None,
            "snapshot": (
                "artifacts/runs/run-20261101-001/final-a11y.yml"
            ),
            "screenshot": None,
            "networkSummary": None,
            "consoleSummary": None,
        },
        "classification": {
            "category": "unknown",
            "confidence": 0.4,
            "reviewRequired": True,
            "summary": "探索结果不能替代确定性 Runner 结论。",
        },
        "assumptions": [
            "未调用确定性 Runner，因此不能作为发布门禁。"
        ],
        "versions": {
            "codex": "0.166.0-alpha.5.1",
            "playwrightMcp": "0.0.84",
            "skill": "ui-test-orchestrator@0.1.0",
        },
        "error": None,
    }


def test_observed_result_matches_schema():
    errors = validate_instance(create_observed_result(), SCHEMA_PATH)
    assert not errors, "\n".join(format_schema_errors(errors))


def test_observed_result_cannot_claim_authoritative_status():
    result = create_observed_result()
    result["authoritativeStatus"] = "passed"

    assert validate_instance(result, SCHEMA_PATH)

