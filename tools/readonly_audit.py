#!/usr/bin/env python3
"""Run an ASDI conformance auditor with no write access to the candidate.

The auditor container receives an exact Git commit through a read-only mount,
has no network, no Docker socket, no Git credentials and no environment
inherited from the host.  Reports are written to a caller-owned directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_OVERALL_RESULTS = {"PASS", "FAIL", "BLOCKED", "CONFORMS_WITH_GAPS"}
REQUIRED_REPORT_FIELDS = {
    "schema_version",
    "audit_date",
    "repo",
    "branch",
    "base_commit",
    "candidate_commit",
    "build_phase",
    "scope",
    "spec_set",
    "source_complete",
    "overall_result",
    "executive_result",
    "conformance_matrix",
    "findings",
    "tests_executed",
    "adversarial_checks",
    "phase_exit_decision",
    "next_actions",
    "independent",
}


def build_command(
    *,
    docker: str,
    image: str,
    candidate: Path,
    specs: Path,
    report_dir: Path,
    skill_root: Path,
    auditor_command: list[str],
    audit_commit: str | None = None,
) -> list[str]:
    candidate = candidate.resolve()
    specs = specs.resolve()
    skill_root = skill_root.resolve()
    report_dir = report_dir.resolve()
    for label, path in (
        ("candidate", candidate),
        ("specs", specs),
        ("skill_root", skill_root),
    ):
        if not path.is_dir():
            raise ValueError(f"{label} must be an existing directory: {path}")
    if not auditor_command:
        raise ValueError("auditor command must not be empty")
    if any(
        arg.lower() in {"docker", "/var/run/docker.sock"} for arg in auditor_command
    ):
        raise ValueError(
            "auditor command may not invoke Docker or mount the Docker socket"
        )
    if any(
        "GITHUB" in token.upper() or "TOKEN" in token.upper()
        for token in auditor_command
    ):
        raise ValueError("auditor command may not contain token assignments")
    entrypoint = auditor_command[0]
    auditor_arguments = auditor_command[1:]
    return [
        docker,
        "run",
        "--rm",
        "--name",
        f"asdi-readonly-audit-{uuid.uuid4().hex[:12]}",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=256m",
        "--user",
        "1001:1001",
        "--mount",
        f"type=bind,source={candidate},destination=/workspace,readonly",
        "--mount",
        f"type=bind,source={specs},destination=/opt/asdi/specs,readonly",
        "--mount",
        f"type=bind,source={skill_root},destination=/opt/asdi/skill,readonly",
        "--mount",
        f"type=bind,source={report_dir},destination=/reports",
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "ASDI_AUDIT_MODE=read_only",
        "--env",
        f"ASDI_AUDIT_COMMIT={audit_commit or 'unknown'}",
        "--entrypoint",
        entrypoint,
        image,
        *auditor_arguments,
    ]


def resolve_commit(repo: Path, revision: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"cannot resolve audit revision: {completed.stderr.strip()}")
    return completed.stdout.strip()


def export_commit(repo: Path, revision: str, destination: Path) -> str:
    """Export one exact Git commit into destination and return its full SHA."""

    commit = resolve_commit(repo, revision)
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination.parent / f".audit-{commit}-{uuid.uuid4().hex}.zip"
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "archive",
            "--format=zip",
            "--output",
            str(archive),
            commit,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        archive.unlink(missing_ok=True)
        raise ValueError(f"cannot export audit revision: {completed.stderr.strip()}")
    try:
        candidate_root = destination.resolve()
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = candidate_root / member.filename
                try:
                    target.relative_to(candidate_root)
                except ValueError as error:
                    raise ValueError(
                        f"unsafe archive path: {member.filename}"
                    ) from error
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
    finally:
        archive.unlink(missing_ok=True)
    return commit


def validate_audit_report(path: Path, audit_commit: str) -> dict[str, Any]:
    validation: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "valid": False,
        "failures": [],
    }
    if not path.is_file():
        validation["failures"].append("auditor did not write report")
        return validation
    try:
        report = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        validation["failures"].append(f"invalid report JSON: {error}")
        return validation
    if not isinstance(report, dict):
        validation["failures"].append("report is not an object")
        return validation
    missing = sorted(REQUIRED_REPORT_FIELDS - set(report))
    unexpected = sorted(set(report) - REQUIRED_REPORT_FIELDS)
    if missing:
        validation["failures"].append(f"missing report fields: {', '.join(missing)}")
    if unexpected:
        validation["failures"].append(f"unexpected report fields: {', '.join(unexpected)}")
    if report.get("candidate_commit") != audit_commit:
        validation["failures"].append("candidate_commit does not match audited revision")
    if report.get("independent") is not True:
        validation["failures"].append("independent must be true")
    if report.get("overall_result") not in ALLOWED_OVERALL_RESULTS:
        validation["failures"].append("invalid overall_result")
    for field in (
        "conformance_matrix",
        "findings",
        "tests_executed",
        "adversarial_checks",
    ):
        if not isinstance(report.get(field), list):
            validation["failures"].append(f"{field} must be an array")
    validation["valid"] = not validation["failures"]
    validation["report"] = report
    return validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", default=os.environ.get("ASDI_DOCKER", "docker"))
    parser.add_argument("--image", default="safeclaw-us-egress:cc-2.1.283")
    parser.add_argument("--candidate", type=Path, default=Path.cwd())
    parser.add_argument("--git-repo", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--specs", type=Path, default=Path("reference"))
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=Path("skills/asdi-build-conformance"),
    )
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument(
        "--report-name",
        default="conformance-report.json",
    )
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument(
        "auditor",
        nargs=argparse.REMAINDER,
        help="Auditor command executed inside the isolated container.",
    )
    arguments = parser.parse_args(argv)
    if arguments.auditor and arguments.auditor[0] == "--":
        arguments.auditor.pop(0)
    if arguments.git_repo and not arguments.commit:
        parser.error("--commit is required with --git-repo")
    report_dir = arguments.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time()

    def utc_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def write_wrapper_report(report: dict[str, Any]) -> None:
        atomic_path = report_dir / ".wrapper-report.tmp"
        atomic_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        os.replace(atomic_path, report_dir / "wrapper-report.json")

    def reject(reason: str) -> int:
        write_wrapper_report(
            {
                "schema_version": "asdi.readonly-audit-wrapper/v1",
                "completed_at": utc_timestamp(),
                "accepted": False,
                "audit_commit": audit_commit,
                "reason": reason,
            }
        )
        return 3

    with tempfile.TemporaryDirectory(
        prefix="asdi-readonly-audit-candidate."
    ) as temporary:
        candidate = arguments.candidate
        audit_commit = arguments.commit
        if arguments.git_repo:
            candidate = Path(temporary) / "candidate"
            audit_commit = export_commit(
                arguments.git_repo,
                arguments.commit,
                candidate,
            )
        if not candidate.is_dir():
            parser.error(f"candidate is not a directory: {candidate}")
        command = build_command(
            docker=arguments.docker,
            image=arguments.image,
            candidate=candidate,
            specs=arguments.specs,
            report_dir=report_dir,
            skill_root=arguments.skill_root,
            auditor_command=arguments.auditor,
            audit_commit=audit_commit,
        )
        invocation = {
            "argv": command,
            "shell": shlex.join(command),
            "audit_commit": audit_commit,
            "candidate": str(candidate),
        }
        invocation_path = report_dir / "invocation.json"
        invocation_path.write_text(
            json.dumps(invocation, indent=2, sort_keys=True) + "\n"
        )
        execution = {"timeout_seconds": arguments.timeout_seconds}
        try:
            completed = subprocess.run(
                command,
                check=False,
                timeout=arguments.timeout_seconds,
            )
        except (subprocess.TimeoutExpired, TimeoutError):
            execution.update(
                {
                    "exit_code": None,
                    "duration_seconds": round(time.time() - started_at, 3),
                    "timed_out": True,
                }
            )
            execution_path = report_dir / "execution.json"
            execution_path.write_text(
                json.dumps(execution, indent=2, sort_keys=True) + "\n"
            )
            return 3
        audit_report_path = report_dir / arguments.report_name
        report_validation = validate_audit_report(audit_report_path, audit_commit)
        report = report_validation.get("report")
        execution.update(
            {
                "exit_code": completed.returncode,
                "duration_seconds": round(time.time() - started_at, 3),
                "timed_out": False,
                "auditor_exit_accepted": completed.returncode == 0,
                "report_validation": report_validation,
            }
        )
        execution_path = report_dir / "execution.json"
        execution_path.write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n")
        if completed.returncode != 0:
            return reject("auditor command failed")
        if not report_validation["valid"]:
            return reject("auditor report invalid")
        report = json.loads(audit_report_path.read_text())
        accepted = report.get("overall_result") in {"PASS", "CONFORMS_WITH_GAPS"}
        write_wrapper_report(
            {
                "schema_version": "asdi.readonly-audit-wrapper/v1",
                "completed_at": utc_timestamp(),
                "accepted": accepted,
                "audit_commit": audit_commit,
                "auditor_result": report.get("overall_result"),
                "report": str(audit_report_path),
            }
        )
        return 0 if accepted else 4


if __name__ == "__main__":
    raise SystemExit(main())
