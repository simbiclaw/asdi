#!/usr/bin/env python3
"""Run REV K static gates in the verifier container."""

from __future__ import annotations

import subprocess
import re
import time
from typing import Any


def kill_and_remove(docker: str, container: str) -> list[dict[str, Any]]:
    """Force-remove one container without allowing cleanup failure to mask red."""

    cleanup: list[dict[str, Any]] = []
    for command in (
        [docker, "kill", container],
        [docker, "rm", "-f", container],
    ):
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            cleanup.append(
                {
                    "command": command,
                    "exit_code": completed.returncode,
                }
            )
        except (OSError, subprocess.SubprocessError) as error:
            cleanup.append(
                {
                    "command": command,
                    "exit_code": None,
                    "error": str(error),
                }
            )
    return cleanup


def run_checks(
    *,
    docker: str,
    image: str,
    manifest: dict[str, Any],
    run_id: str,
    commit: str,
    mounts: list[str],
    timeout_scale: float = 1.0,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for check in manifest.get("checks", []):
        started = time.time()
        blocking = bool(check.get("blocking", True))
        timed_out = False
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", str(check["id"]))
        container = f"asdi-static-{run_id}-{safe_id}"[:200]
        try:
            completed = subprocess.run(
                [
                    docker,
                    "run",
                    "--rm",
                    "--name",
                    container,
                    "--network",
                    "none",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=64m",
                    *(
                        item
                        for mount in mounts
                        for item in ("--mount", mount)
                    ),
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
            status = "pass" if exit_code == 0 else "fail"
        except subprocess.TimeoutExpired as error:
            timed_out = True
            exit_code = None
            stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else str(error.stdout or "")
            stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else str(error.stderr or "")
            status = "error"
            cleanup = kill_and_remove(docker, container)
        except OSError as error:
            exit_code = None
            stdout = ""
            stderr = str(error)
            status = "error"
        checks.append(
            {
                "id": f"static:{check['id']}",
                "status": status,
                "blocking": blocking,
                "exit_code": exit_code,
                "duration_seconds": round(time.time() - started, 3),
                "stdout": stdout[-4000:],
                "stderr": stderr[-4000:],
                "container": container,
                "timeout_killed": timed_out,
                "timeout_cleanup": cleanup if timed_out else [],
            }
        )
    return checks


def gate_passes(checks: list[dict[str, Any]]) -> bool:
    blocking = [item for item in checks if item.get("blocking", True)]
    blocking_passes = bool(blocking) and all(item["status"] == "pass" for item in blocking)
    advisory_has_error = any(
        item.get("blocking", True) is False
        and item.get("status") in {"error", "blocked"}
        for item in checks
    )
    return blocking_passes and not advisory_has_error
