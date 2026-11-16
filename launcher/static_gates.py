#!/usr/bin/env python3
"""Run REV K static gates in the verifier container."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any


def run_checks(
    *,
    docker: str,
    image: str,
    workspace: Path,
    manifest: dict[str, Any],
    run_id: str,
    commit: str,
    timeout_scale: float = 1.0,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for check in manifest.get("checks", []):
        started = time.time()
        try:
            completed = subprocess.run(
                [
                    docker,
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=64m",
                    "--mount",
                    f"type=bind,source={workspace},destination=/workspace",
                    "--workdir",
                    "/workspace",
                    "--env",
                    f"ASDI_RUN_ID={run_id}",
                    "--env",
                    "ASDI_EVIDENCE_DIR=/workspace/.asdi-evidence",
                    image,
                    *check["command"],
                ],
                capture_output=True,
                text=True,
                timeout=float(check["timeout_seconds"]) * timeout_scale,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            status = "pass" if exit_code == 0 and check.get("blocking", True) else "fail"
        except subprocess.TimeoutExpired as error:
            exit_code = None
            stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else str(error.stdout or "")
            stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else str(error.stderr or "")
            status = "error"
        except OSError as error:
            exit_code = None
            stdout = ""
            stderr = str(error)
            status = "error"
        checks.append(
            {
                "id": f"static:{check['id']}",
                "status": status,
                "exit_code": exit_code,
                "duration_seconds": round(time.time() - started, 3),
                "stdout": stdout[-4000:],
                "stderr": stderr[-4000:],
            }
        )
    return checks


def gate_passes(checks: list[dict[str, Any]]) -> bool:
    return bool(checks) and all(item["status"] == "pass" for item in checks)
