#!/usr/bin/env python3
"""Explicit-command adapter for verifier-only PR/main verification."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .verification import main_verification_event_payload, verification_event_payload


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
VERIFIER_STATUSES = {"succeeded", "failed"}
VERIFICATION_SOURCES = {"pr-head", "main"}
FORBIDDEN_TOKEN_MARKERS = ("api_key", "authorization", "password", "secret", "token")


def ci_status_from_checks(checks: Any) -> str:
    """Derive the immutable ``ci`` result from named static-gate checks."""

    if not isinstance(checks, list):
        return "error"
    static_checks = [
        check
        for check in checks
        if isinstance(check, dict) and str(check.get("id", "")).startswith("static:")
    ]
    if not static_checks:
        return "error"
    if any(check.get("status") in {"error", "blocked"} for check in static_checks):
        return "error"
    if any(
        check.get("blocking", True) is True and check.get("status") != "pass"
        for check in static_checks
    ):
        return "fail"
    if any(check.get("blocking", True) is False and check.get("status") == "fail" for check in static_checks):
        return "pass"
    if all(check.get("status") == "pass" for check in static_checks):
        return "pass"
    return "error"


@dataclass(frozen=True)
class VerificationCommand:
    """Absolute, shell-free verifier command with bounded execution."""

    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = 900.0
    source: str = "pr-head"

    def __post_init__(self) -> None:
        if not self.argv or not Path(self.argv[0]).is_absolute():
            raise ValueError("verifier executable must be absolute")
        if self.timeout_seconds <= 0:
            raise ValueError("verifier timeout must be positive")
        if any(not isinstance(token, str) or not token for token in self.argv):
            raise ValueError("verifier arguments must be non-empty strings")
        if any(
            marker in token.lower()
            for token in self.argv
            for marker in FORBIDDEN_TOKEN_MARKERS
        ):
            raise ValueError("verifier command may not contain credential-like names")
        if self.source not in VERIFICATION_SOURCES:
            raise ValueError("verification source must be pr-head or main")

    def build(self, *, head_sha: str, output: Path) -> tuple[list[str], dict[str, str]]:
        placeholders = {"head": head_sha, "output": str(output)}
        command = [token.format(**placeholders) for token in self.argv]
        if any(
            not isinstance(token, str) or any(ord(char) < 32 for char in token)
            for token in command
        ):
            raise ValueError("verifier arguments must be printable strings")
        environment = {
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "TMPDIR": "/tmp",
            "ASDI_VERIFICATION_MODE": "verifier_only",
            "ASDI_VERIFICATION_SOURCE": self.source,
        }
        return command, environment


def validate_verifier_result(
    report: Any,
    head_sha: str,
    *,
    source: str = "pr-head",
) -> list[str]:
    """Validate a launcher verifier-only result without trusting its status."""

    failures: list[str] = []
    if not isinstance(report, dict):
        return ["verifier output is not an object"]
    required = {
        "schema_version",
        "run_id",
        "status",
        "revision",
        "commit",
        "source",
        "checks",
        "evidence",
        "runtime",
    }
    missing = sorted(required - set(report))
    if missing:
        failures.append(f"missing fields: {', '.join(missing)}")
    if report.get("schema_version") != "asdi.verifier-only-result/v1":
        failures.append("unsupported verifier result schema")
    if report.get("status") not in VERIFIER_STATUSES:
        failures.append("verifier status is invalid")
    if report.get("commit") != head_sha or report.get("revision") != head_sha:
        failures.append("verifier result is not bound to target commit")
    if report.get("source") != source:
        failures.append(f"verification requires source {source}")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        failures.append("verifier checks must be a non-empty array")
    elif not any(
        isinstance(check, dict) and str(check.get("id", "")).startswith("static:")
        for check in checks
    ):
        failures.append("verifier checks must include static-gate results")
    runtime = report.get("runtime")
    if not isinstance(runtime, dict):
        failures.append("verifier runtime evidence is missing")
    else:
        if runtime.get("network") != "none":
            failures.append("verification requires runtime network none")
        if runtime.get("socket_mounted") is not False:
            failures.append("verification forbids a Docker socket mount")
        if runtime.get("secrets_mounted") is not False:
            failures.append("verification forbids mounted secrets")
        if runtime.get("agent_started") is not False:
            failures.append("verification forbids starting an agent")

    evidence = report.get("evidence")
    if not isinstance(evidence, dict):
        failures.append("verifier evidence is not an object")
        return failures
    if evidence.get("valid") is not True:
        failures.append("verifier evidence is not valid")
    if not isinstance(evidence.get("manifest_id"), str) or not evidence["manifest_id"]:
        failures.append("verifier evidence has no manifest_id")
    result = evidence.get("result")
    if not isinstance(result, dict):
        failures.append("verifier evidence has no result")
        return failures
    if result.get("schema") != 2:
        failures.append("verifier evidence result schema must be 2")
    if result.get("commit") != head_sha:
        failures.append("verifier evidence result is not bound to target commit")
    if result.get("run_id") != report.get("run_id"):
        failures.append("verifier evidence run_id does not match result")
    features = result.get("features")
    if not isinstance(features, list) or not features:
        failures.append("verifier evidence has no features")
    statement = evidence.get("statement")
    if not isinstance(statement, dict):
        failures.append("verifier evidence has no statement")
        return failures
    subject = statement.get("subject")
    if (
        not isinstance(subject, list)
        or len(subject) != 1
        or not isinstance(subject[0], dict)
        or subject[0].get("digest", {}).get("gitCommit") != head_sha
    ):
        failures.append("verifier evidence subject is not bound to target commit")
    if statement.get("predicate", {}).get("source") != source:
        failures.append(f"verification requires evidence statement source {source}")
    return failures


def run_verification(
    *,
    command: VerificationCommand,
    head_sha: str,
) -> dict[str, Any]:
    """Execute one verifier command and normalize its fail-closed result."""

    if not isinstance(head_sha, str) or not FULL_SHA.fullmatch(head_sha):
        raise ValueError("verification head must be a 40-character lowercase SHA")
    execution_run_id = f"rvx-{uuid.uuid4()}"
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="asdi-verifier-command.") as temporary:
        root = Path(temporary)
        output_path = root / "verifier-result.json"
        argv, environment = command.build(head_sha=head_sha, output=output_path)
        timed_out = False
        exit_code: int | None = None
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
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            timed_out = True
            stdout = error.stdout if isinstance(error.stdout, str) else ""
            stderr = error.stderr if isinstance(error.stderr, str) else ""

        try:
            report = json.loads(output_path.read_text()) if output_path.is_file() else None
        except (OSError, json.JSONDecodeError) as error:
            report = None
            stderr = f"{stderr}\ninvalid verifier JSON: {error}".strip()

        validation_failures = validate_verifier_result(
            report,
            head_sha,
            source=command.source,
        )
        report_dict = report if isinstance(report, dict) else {}
        report_run_id = report_dict.get("run_id")
        run_id = (
            report_run_id
            if isinstance(report_run_id, str) and report_run_id
            else execution_run_id
        )
        status = (
            report_dict.get("status")
            if not validation_failures
            and report_dict.get("status") in VERIFIER_STATUSES
            else "failed"
        )
        if status == "succeeded" and exit_code != 0:
            validation_failures.append("successful verifier exited nonzero")
            status = "failed"
        derived_ci = ci_status_from_checks(report_dict.get("checks", []))
        if status == "succeeded" and derived_ci != "pass":
            validation_failures.append(
                f"successful verifier has derived ci status {derived_ci}"
            )
            status = "failed"
        evidence = report_dict.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {"valid": False}
        runtime = report_dict.get("runtime")
        if not isinstance(runtime, dict):
            runtime = {
                "network": "unknown",
                "socket_mounted": True,
                "secrets_mounted": True,
                "agent_started": True,
            }
        manifest_id = evidence.get("manifest_id")
        if not isinstance(manifest_id, str) or not manifest_id:
            manifest_id = "m-unavailable-" + hashlib.sha256(
                f"{head_sha}:{run_id}".encode()
            ).hexdigest()[:16]
        result = {
            "schema_version": "asdi.verification-execution/v1",
            "run_id": run_id,
            "status": status,
            "revision": head_sha,
            "commit": head_sha,
            "source": command.source,
            "checks": report_dict.get("checks", []),
            "ci_status": derived_ci,
            "evidence": evidence,
            "runtime": runtime,
            "execution": {
                "name": command.name,
                "argv": argv,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "duration_seconds": round(time.time() - started, 3),
                "validation_failures": validation_failures,
                "stdout": stdout[-8000:],
                "stderr": stderr[-8000:],
            },
        }
        return result


def verification_execution_event_payload(
    *,
    packet: dict[str, Any],
    result: dict[str, Any],
    ci_status: str,
) -> dict[str, Any]:
    """Map an executed verifier result into the durable verification contract."""

    head_sha = packet.get("head_sha")
    if result.get("schema_version") != "asdi.verification-execution/v1":
        raise ValueError("unsupported verification execution schema")
    source = result.get("source")
    if source not in VERIFICATION_SOURCES:
        raise ValueError("verification execution has invalid source")
    if result.get("commit") != head_sha:
        raise ValueError("verification execution is not bound to target commit")
    evidence = result.get("evidence")
    derived_ci = result.get("ci_status")
    if derived_ci not in {"pass", "fail", "blocked", "error"}:
        derived_ci = "error"
    mismatches: list[str] = []
    if ci_status != derived_ci:
        mismatches.append(
            f"declared ci status {ci_status!r} does not match derived status {derived_ci!r}"
        )
    if isinstance(evidence, dict) and evidence.get("valid") is True:
        try:
            if source == "pr-head":
                payload = verification_event_payload(
                    packet=packet,
                    evidence=evidence,
                    ci_status=ci_status,
                )
            else:
                payload = main_verification_event_payload(
                    commit=head_sha,
                    evidence=evidence,
                    ci_status=ci_status,
                )
            if result.get("status") != "succeeded":
                payload["verifier"]["status"] = "fail"
                payload["verifier"]["failures"] = [
                    "verifier execution status is not succeeded",
                    *mismatches,
                ]
            elif mismatches:
                payload["verifier"]["status"] = "fail"
                payload["verifier"]["failures"] = mismatches
            payload["statuses"]["ci"] = derived_ci
            return payload
        except ValueError:
            pass

    failures = list(result.get("execution", {}).get("validation_failures", []))
    if not failures:
        failures = ["verifier command did not produce valid target evidence"]
    manifest_id = (
        evidence.get("manifest_id")
        if isinstance(evidence, dict)
        and isinstance(evidence.get("manifest_id"), str)
        and evidence["manifest_id"]
        else "m-unavailable-" + hashlib.sha256(head_sha.encode()).hexdigest()[:16]
    )
    if source == "pr-head":
        return {
            "pr_number": packet["pr_number"],
            "head_sha": head_sha,
            "statuses": {"ci": derived_ci},
            "verifier": {
                "candidate_commit": head_sha,
                "status": "fail",
                "manifest_id": manifest_id,
                "run_id": result["run_id"],
                "failures": failures,
            },
        }
    return {
        "commit": head_sha,
        "statuses": {"ci": derived_ci},
        "verifier": {
            "candidate_commit": head_sha,
            "status": "fail",
            "manifest_id": manifest_id,
            "run_id": result["run_id"],
            "failures": failures,
        },
    }
