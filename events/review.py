#!/usr/bin/env python3
"""Explicit-command wrapper for the REV K Pass 1 review pass."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_operational_defaults


ALLOWED_STATUS = {"pass", "fail", "blocked"}
ALLOWED_BUCKETS = {"act", "consider", "noted", "dismissed"}
FORBIDDEN_TOKEN_MARKERS = ("api_key", "authorization", "password", "secret", "token")


@dataclass(frozen=True)
class ReviewCommand:
    """Absolute, shell-free reviewer command with bounded execution."""

    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = field(
        default_factory=lambda: load_operational_defaults().review_timeout_seconds
    )
    independent_family: bool = False

    def __post_init__(self) -> None:
        if not self.argv or not Path(self.argv[0]).is_absolute():
            raise ValueError("reviewer executable must be absolute")
        if self.timeout_seconds <= 0:
            raise ValueError("reviewer timeout must be positive")
        if any(
            marker in token.lower()
            for token in self.argv
            for marker in FORBIDDEN_TOKEN_MARKERS
        ):
            raise ValueError("reviewer command may not contain credential-like names")

    def build(self, *, packet: Path, diff: Path, output: Path) -> tuple[list[str], dict[str, str]]:
        placeholders = {
            "packet": str(packet),
            "diff": str(diff),
            "output": str(output),
        }
        command = [token.format(**placeholders) for token in self.argv]
        if any(not isinstance(token, str) or any(ord(char) < 32 for char in token) for token in command):
            raise ValueError("reviewer arguments must be printable strings")
        environment = {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
            "ASDI_REVIEW_MODE": "read_only",
        }
        return command, environment


def validate_review_report(report: Any, reviewed_commit: str) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    if not isinstance(report, dict):
        return {"status": "blocked"}, ["reviewer output is not an object"]
    required = {
        "schema_version",
        "pass",
        "model",
        "independent_family",
        "reviewed_commit",
        "status",
        "findings",
    }
    missing = sorted(required - set(report))
    unexpected = sorted(set(report) - required)
    if missing:
        failures.append(f"missing fields: {', '.join(missing)}")
    if unexpected:
        failures.append(f"unexpected fields: {', '.join(unexpected)}")
    if report.get("schema_version") != "asdi.review-result/v1":
        failures.append("unsupported review result schema")
    if report.get("pass") != "review":
        failures.append("review pass must be review")
    if not isinstance(report.get("model"), str) or not report.get("model"):
        failures.append("model must be a non-empty string")
    if report.get("independent_family") not in {True, False, "unavailable"}:
        failures.append("invalid independent_family")
    if report.get("reviewed_commit") != reviewed_commit:
        failures.append("reviewed_commit does not match PR head")
    if report.get("status") not in ALLOWED_STATUS:
        failures.append("invalid review status")
    findings = report.get("findings")
    if not isinstance(findings, list):
        failures.append("findings must be an array")
    else:
        for index, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                failures.append(f"finding {index} is not an object")
                continue
            if finding.get("bucket") not in ALLOWED_BUCKETS:
                failures.append(f"finding {index} has invalid bucket")
            if finding.get("bucket") == "act" and not finding.get("evidence"):
                failures.append(f"act finding {index} has no evidence")
    normalized = report if isinstance(report, dict) else {"status": "blocked"}
    if failures:
        normalized = {
            **normalized,
            "status": "blocked",
            "findings": [
                *(
                    normalized.get("findings", [])
                    if isinstance(normalized.get("findings"), list)
                    else []
                ),
                {"bucket": "act", "claim": "review output failed validation", "evidence": "; ".join(failures)},
            ],
        }
    return normalized, failures


def run_review(
    *,
    packet: dict[str, Any],
    diff: str,
    command: ReviewCommand,
) -> dict[str, Any]:
    reviewed_commit = str(packet.get("head_sha", ""))
    if not reviewed_commit:
        raise ValueError("review packet is missing head_sha")
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="asdi-review-pass.") as temporary:
        root = Path(temporary)
        packet_path = root / "review-packet.json"
        diff_path = root / "changed.diff"
        output_path = root / "review-result.json"
        packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
        diff_path.write_text(diff)
        argv, environment = command.build(
            packet=packet_path,
            diff=diff_path,
            output=output_path,
        )
        timed_out = False
        exit_code = None
        try:
            completed = subprocess.run(
                argv,
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=command.timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as error:
            timed_out = True
            stdout = error.stdout if isinstance(error.stdout, str) else ""
            stderr = error.stderr if isinstance(error.stderr, str) else ""
        else:
            stdout = completed.stdout
            stderr = completed.stderr
        if output_path.is_file():
            try:
                report = json.loads(output_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                report = {"status": "blocked", "findings": [{"claim": f"invalid reviewer JSON: {error}"}]}
        else:
            reason = "reviewer timed out" if timed_out else "reviewer did not write output"
            report = {"status": "blocked", "findings": [{"claim": reason}]}
        normalized, failures = validate_review_report(report, reviewed_commit)
        execution_failures: list[str] = []
        if timed_out:
            execution_failures.append("reviewer timed out")
        elif exit_code != 0:
            execution_failures.append(f"reviewer exited nonzero ({exit_code})")
        if execution_failures:
            failures.extend(execution_failures)
            findings = normalized.get("findings")
            normalized = {
                **normalized,
                "status": "blocked",
                "findings": [
                    *(findings if isinstance(findings, list) else []),
                    {
                        "bucket": "act",
                        "claim": "reviewer execution did not succeed",
                        "evidence": "; ".join(execution_failures),
                    },
                ],
            }
        result = {
            "schema_version": "asdi.review-execution/v1",
            "pass": "review",
            "model": normalized.get("model", "unknown"),
            "independent_family": command.independent_family,
            "reviewed_commit": reviewed_commit,
            "status": normalized.get("status", "blocked"),
            "findings": normalized.get("findings", []),
            "execution": {
                "argv": argv,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "duration_seconds": round(time.time() - started, 3),
                "stdout_path": "review-stdout.log",
                "stderr_path": "review-stderr.log",
                "output_path": str(output_path),
                "validation_failures": failures,
            },
        }
        result["execution"]["stdout"] = stdout[-8000:]
        result["execution"]["stderr"] = stderr[-8000:]
        return result


def review_event_payload(
    *,
    packet: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Convert an executed review into the durable workflow-event contract.

    Execution provenance and captured model output remain in the review result.
    The journal receives only the normalized gate evidence.
    """

    pr_number = packet.get("pr_number")
    head_sha = packet.get("head_sha")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise ValueError("review packet has no valid pr_number")
    if not isinstance(head_sha, str) or not head_sha:
        raise ValueError("review packet has no valid head_sha")
    if result.get("schema_version") != "asdi.review-execution/v1":
        raise ValueError("unsupported review execution schema")
    if result.get("reviewed_commit") != head_sha:
        raise ValueError("review result is not bound to packet head")
    status = result.get("status")
    if status not in ALLOWED_STATUS:
        raise ValueError("review result has invalid status")
    normalized = {
        key: result[key]
        for key in (
            "schema_version",
            "pass",
            "model",
            "independent_family",
            "reviewed_commit",
            "status",
            "findings",
        )
    }
    normalized["passed"] = status == "pass"
    return {
        "pr_number": pr_number,
        "head_sha": head_sha,
        "review": normalized,
    }
