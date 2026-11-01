from __future__ import annotations

import json
import os
from pathlib import Path

import _bootstrap  # noqa: F401

from examples.login_app.server import start_server
from ui_test_poc.contract import load_contract
from ui_test_poc.runner import run_contract

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    port = int(os.environ.get("DEMO_FAILURE_PORT", "4174"))
    app = start_server(port=port)
    os.environ["WEB_BASE_URL"] = app.url
    os.environ.setdefault("DEMO_USER", "demo")
    os.environ.setdefault("DEMO_INVALID_PASSWORD", "invalid-password")

    try:
        contract, secrets = load_contract(
            ROOT / "tests/contracts/LOGIN-FAIL-001.yaml"
        )
        result = run_contract(
            contract,
            secret_values=secrets,
            output_root=ROOT / "artifacts/runs",
            headless=os.environ.get("HEADED") != "1",
        )

        required_evidence = [
            "trace",
            "screenshot",
            "accessibilitySnapshot",
            "network",
            "console",
        ]
        missing = [
            name
            for name in required_evidence
            if not result["evidence"].get(name)
        ]
        for name in required_evidence:
            path = result["evidence"].get(name)
            if path and not Path(path).is_file():
                raise RuntimeError(f"证据文件不存在: {path}")

        if result["status"] != "failed" or missing:
            raise RuntimeError(
                "失败场景验证未达预期: "
                f"status={result['status']}, missing={','.join(missing)}"
            )

        print(
            json.dumps(
                {
                    "status": result["status"],
                    "runId": result["runId"],
                    "runDir": os.path.relpath(result["runDir"], ROOT),
                    "evidence": result["evidence"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())

