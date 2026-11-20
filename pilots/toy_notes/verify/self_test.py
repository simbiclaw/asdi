#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
VERIFY = PRODUCT_ROOT / "verify" / "bin" / "verify"
RUN_ID_PATTERN = re.compile(r"^r-[A-Za-z0-9-]+$")
STATUSES = {"pass", "fail", "blocked", "error", "not_applicable"}
CONTROLS = {"caught", "missed", "not_applicable"}


def self_test_feature() -> str:
    manifest = (PRODUCT_ROOT / "verify" / "verify.yaml").read_text(encoding="utf-8")
    match = re.search(r"self_test:\s*\{\s*feature:\s*([^}\s]+)\s*\}", manifest)
    if match is None:
        raise ValueError("verify.yaml has no self_test feature")
    return match.group(1)


def validate_result(result: dict, expected_run_id: str) -> list[str]:
    failures: list[str] = []
    if result.get("schema") != 2:
        failures.append("schema must be 2")
    if result.get("run_id") != expected_run_id or not RUN_ID_PATTERN.match(str(result.get("run_id", ""))):
        failures.append("run_id mismatch or invalid pattern")
    if not result.get("commit"):
        failures.append("commit is empty")
    features = result.get("features")
    if not isinstance(features, list) or not features:
        failures.append("features must be a non-empty array")
        return failures
    for feature in features:
        name = feature.get("id", "<unknown>")
        if feature.get("status") != "pass" or feature.get("status") not in STATUSES:
            failures.append(f"{name} status is not pass")
        if feature.get("control") != "caught" or feature.get("control") not in CONTROLS:
            failures.append(f"{name} control is not caught")
        if not feature.get("evidence"):
            failures.append(f"{name} has no evidence")
        if not feature.get("limits"):
            failures.append(f"{name} has no limits")
    return failures


def main() -> int:
    run_id = "r-selftest-" + uuid.uuid4().hex
    configured = os.environ.get("ASDI_EVIDENCE_DIR")
    evidence = (
        Path(configured) / f"self-test-{run_id}"
        if configured
        else Path(tempfile.gettempdir()) / f"asdi-toy-notes-self-test-{run_id}"
    )
    environment = os.environ.copy()
    environment["ASDI_EVIDENCE_DIR"] = str(evidence)
    environment["ASDI_RUN_ID"] = run_id
    environment["ASDI_HEAD"] = str(PRODUCT_ROOT)
    environment.pop("TOY_NOTES_INJECT_DEFECT", None)
    environment["NOTES_UI_ENABLED"] = "0"

    try:
        feature = self_test_feature()
        steps = [
            ("launch", []),
            ("doctor", []),
            ("drive", [feature]),
            ("control", [feature]),
            ("cleanup", []),
        ]
        for name, arguments in steps:
            completed = subprocess.run(
                [str(VERIFY), name, *arguments],
                cwd=PRODUCT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            print(f"{name}: exit={completed.returncode} {completed.stdout.strip()}")
            if completed.returncode != 0:
                print(completed.stderr.strip(), file=sys.stderr)
                return 1

        result_path = evidence / "result.json"
        if not result_path.is_file():
            print(f"self-test: result.json missing at {result_path}", file=sys.stderr)
            return 1
        result = json.loads(result_path.read_text(encoding="utf-8"))
        failures = validate_result(result, run_id)
        if failures:
            for failure in failures:
                print(f"self-test invalid: {failure}", file=sys.stderr)
            return 1
        if not evidence.is_dir() or not result_path.is_file():
            print("self-test: cleanup removed evidence", file=sys.stderr)
            return 1
        print(f"self-test: pass; result validates; evidence preserved at {evidence}")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"self-test error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
