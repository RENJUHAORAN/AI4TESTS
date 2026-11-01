from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

EXPECTED_SKILLS = [
    "ui-test-authoring",
    "ui-test-orchestrator",
    "ui-test-triage",
]
TIMEOUT_SECONDS = 20


class AppServerClient:
    def __init__(self, executable: str, cwd: Path):
        self._messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._next_id = 1
        self._process = subprocess.Popen(
            [executable, "app-server", "--listen", "stdio://"],
            cwd=cwd,
            env=os.environ.copy(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            name="codex-app-server-stdout",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr,
            name="codex-app-server-stderr",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    @property
    def stderr(self) -> str:
        return "".join(self._stderr_lines).strip()

    def send(self, message: dict[str, Any]) -> None:
        if self._process.stdin is None:
            raise RuntimeError("Codex App Server stdin 不可用")
        self._process.stdin.write(
            json.dumps(message, ensure_ascii=False) + "\n"
        )
        self._process.stdin.flush()

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self.send(
            {
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        deadline = time.monotonic() + TIMEOUT_SECONDS

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"{method} timed out after {TIMEOUT_SECONDS}s"
                )
            try:
                message = self._messages.get(timeout=remaining)
            except queue.Empty as error:
                raise TimeoutError(
                    f"{method} timed out after {TIMEOUT_SECONDS}s"
                ) from error

            if message is None:
                raise RuntimeError(
                    f"Codex App Server exited while waiting for {method}"
                )
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise RuntimeError(
                    json.dumps(message["error"], ensure_ascii=False)
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(
                    f"{method} returned an invalid result"
                )
            return result

    def close(self) -> None:
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)

    def _read_stdout(self) -> None:
        if self._process.stdout is None:
            return
        for line in self._process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._messages.put(message)
        self._messages.put(None)

    def _read_stderr(self) -> None:
        if self._process.stderr is None:
            return
        for line in self._process.stderr:
            self._stderr_lines.append(line)


def same_path(left: str | None, right: Path) -> bool:
    if not left:
        return False
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        str(right.resolve())
    )


def main() -> int:
    cwd = Path.cwd().resolve()
    executable = os.environ.get("CODEX_BIN") or shutil.which("codex")
    if not executable:
        raise RuntimeError("找不到 codex 可执行文件")

    client = AppServerClient(executable, cwd)
    try:
        client.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "ai4tests-skill-verifier",
                    "title": "AI4Tests Skill Verifier",
                    "version": "1.0.0",
                },
                "capabilities": {
                    "experimentalApi": True,
                    "requestAttestation": False,
                },
            },
        )
        client.send({"method": "initialized"})
        response = client.request(
            "skills/list",
            {"cwds": [str(cwd)], "forceReload": True},
        )

        entries = response.get("data", [])
        entry = next(
            (
                item
                for item in entries
                if same_path(item.get("cwd"), cwd)
            ),
            entries[0] if entries else None,
        )
        if entry is None:
            raise RuntimeError("skills/list returned no cwd entry")

        discovered = sorted(
            [
                {
                    "name": skill["name"],
                    "scope": skill.get("scope"),
                    "path": skill.get("path"),
                    "enabled": skill.get("enabled"),
                }
                for skill in entry.get("skills", [])
                if skill.get("name") in EXPECTED_SKILLS
            ],
            key=lambda item: item["name"],
        )
        missing = [
            name
            for name in EXPECTED_SKILLS
            if not any(item["name"] == name for item in discovered)
        ]
        errors = entry.get("errors", [])

        print(
            json.dumps(
                {
                    "cwd": entry.get("cwd"),
                    "discovered": discovered,
                    "missing": missing,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        if errors:
            raise RuntimeError("skills/list reported skill loading errors")
        if len(discovered) != len(EXPECTED_SKILLS):
            raise RuntimeError(
                f"expected {len(EXPECTED_SKILLS)} project skills, "
                f"found {len(discovered)}"
            )
        return 0
    except Exception as error:
        print(str(error))
        if client.stderr:
            print(client.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())

