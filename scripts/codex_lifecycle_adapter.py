#!/usr/bin/env python3
"""Explicit Codex CLI adapter for the local ASDI lifecycle.

This adapter is opt-in.  It runs Codex non-interactively in workspace-write
mode with approvals disabled and validates that the requested artifacts exist.
It does not authorize production access, remote merge, or irreversible actions.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


PROMPT_TEMPLATE = """You are implementing one bounded ASDI lifecycle task.

Mission ID: {mission_id}
Variant: {variant}
Objective: {objective}

Create exactly these files in the current workspace:
1. app.py — a Python 3 CLI with --self-check and --handle.
2. manifest.json — JSON with mission_id, variant, revision, paths, fixture_agent=false.

Behavior requirements:
- --self-check must exit 0 and print JSON with ok=true.
- --handle --scenario normal must exit 0 and print JSON with ok=true.
- For variant "buggy", --handle --scenario load --flag-enabled true must intentionally return ok=false and exit 1.
- For variants "good" and "repair", the load scenario must return ok=true and exit 0.
- Do not use secrets, subprocess, sockets, eval, or exec.
- Do not run git commands, modify outside the workspace, or perform irreversible actions.
- Keep the implementation small and deterministic.

Finish only when both files exist and the applicable checks pass.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument(
        "--variant",
        choices=("good", "buggy", "repair"),
        required=True,
    )
    parser.add_argument(
        "--codex-path",
        default=shutil.which("codex"),
        help="Absolute Codex CLI path; defaults to PATH discovery.",
    )
    parser.add_argument("--timeout", type=float, default=240)
    arguments = parser.parse_args()

    workspace = Path(arguments.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    codex_input = (
        Path(arguments.codex_path).expanduser() if arguments.codex_path else None
    )
    codex = codex_input.resolve() if codex_input else None
    if not codex or not codex.is_file() or not os.access(codex, os.X_OK):
        print(json.dumps({"ok": False, "error": "Codex executable not found"}))
        return 2

    prompt = PROMPT_TEMPLATE.format(
        mission_id=arguments.mission_id,
        variant=arguments.variant,
        objective=arguments.objective,
    )
    last_message = workspace / "agent-last-message.txt"
    command = [
        str(codex),
        "exec",
        "--cd",
        str(workspace),
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "--output-last-message",
        str(last_message),
        prompt,
    ]
    environment = os.environ.copy()
    environment["PATH"] = f"{codex_input.parent}:{environment.get('PATH', '')}"
    completed = subprocess.run(
        command,
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=arguments.timeout,
        check=False,
    )
    (workspace / "codex.stdout.log").write_text(completed.stdout)
    (workspace / "codex.stderr.log").write_text(completed.stderr)
    findings: list[str] = []
    if completed.returncode != 0:
        findings.append(f"Codex exited {completed.returncode}")
    if not (workspace / "app.py").is_file():
        findings.append("app.py was not created")
    manifest_path = workspace / "manifest.json"
    manifest = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            findings.append("manifest.json is not valid JSON")
    else:
        findings.append("manifest.json was not created")
    if manifest.get("fixture_agent") is not False:
        findings.append("manifest does not identify a live adapter")

    result = {
        "ok": not findings,
        "variant": arguments.variant,
        "codex_exit_code": completed.returncode,
        "findings": findings,
        "billing_api_queried": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
