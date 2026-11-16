#!/usr/bin/env python3
"""Three scoped, process-isolated checks used by the local lifecycle."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path


FORBIDDEN = ("BEGIN PRIVATE KEY", "AWS_ACCESS_KEY_ID=", "DOCKER_HOST=", "subprocess", "socket.socket", "eval(", "exec(")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--scope", choices=("correctness", "security", "acceptance"), required=True)
    arguments = parser.parse_args()
    workspace = Path(arguments.workspace)
    app = workspace / "app.py"
    manifest_path = workspace / "manifest.json"
    findings: list[str] = []
    passed = True

    if not app.is_file() or not manifest_path.is_file():
        print(json.dumps({"scope": arguments.scope, "passed": False, "findings": ["app.py and manifest.json are required"]}))
        return 1

    try:
        ast.parse(app.read_text())
        manifest = json.loads(manifest_path.read_text())
    except Exception as error:
        print(json.dumps({"scope": arguments.scope, "passed": False, "findings": [f"artifact parse failed: {error}"]}))
        return 1

    if arguments.scope == "correctness":
        checks = []
        for operation in ("--self-check", "--handle --scenario normal --flag-enabled true"):
            completed = subprocess.run(
                [sys.executable, str(app), *operation.split()],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            try:
                response = json.loads(completed.stdout)
                passed_check = completed.returncode == 0 and response.get("ok") is True
            except json.JSONDecodeError:
                response = {}
                passed_check = False
            checks.append({"operation": operation, "passed": passed_check, "response": response})
            if not passed_check:
                findings.append(f"correctness check failed: {operation}")
        passed = all(check["passed"] for check in checks)
    elif arguments.scope == "security":
        source = app.read_text().lower()
        for token in FORBIDDEN:
            if token.lower() in source:
                findings.append(f"forbidden implementation token: {token}")
        if manifest.get("fixture_agent") not in (True, False):
            findings.append("missing explicit agent provenance marker")
        passed = not findings
    else:
        if manifest.get("variant") not in {"good", "buggy", "repair"}:
            findings.append("invalid artifact variant")
        revision = manifest.get("revision")
        if not (isinstance(revision, str) and revision.strip()) and not (
            isinstance(revision, int) and not isinstance(revision, bool) and revision > 0
        ):
            findings.append("missing artifact revision")
        passed = not findings

    print(json.dumps({"scope": arguments.scope, "passed": passed, "findings": findings}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
