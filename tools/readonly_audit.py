#!/usr/bin/env python3
"""Run an ASDI conformance auditor with no write access to the candidate.

This helper is the enforcement wrapper for verifier-authority escalation option
2.  The auditor container receives the candidate through a read-only mount, has
no network, no Docker socket, no Git credentials and no environment inherited
from the host.  Reports are written to a caller-owned output directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path


def build_command(
    *,
    docker: str,
    image: str,
    candidate: Path,
    specs: Path,
    report_dir: Path,
    skill_root: Path,
    auditor_command: list[str],
) -> list[str]:
    """Return the isolated Docker invocation without executing it."""

    candidate = candidate.resolve()
    specs = specs.resolve()
    skill_root = skill_root.resolve()
    report_dir = report_dir.resolve()
    for label, path in (("candidate", candidate), ("specs", specs), ("skill_root", skill_root)):
        if not path.is_dir():
            raise ValueError(f"{label} must be an existing directory: {path}")
    if not auditor_command:
        raise ValueError("auditor command must not be empty")
    if any(arg.lower() in {"docker", "/var/run/docker.sock"} for arg in auditor_command):
        raise ValueError("auditor command may not invoke Docker or mount the Docker socket")
    if any("GITHUB" in token.upper() or "TOKEN" in token.upper() for token in auditor_command):
        raise ValueError("auditor command may not contain token assignments")

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
        image,
        *auditor_command,
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", default=os.environ.get("ASDI_DOCKER", "docker"))
    parser.add_argument("--image", default="safeclaw-us-egress:cc-2.1.283")
    parser.add_argument("--candidate", type=Path, default=Path.cwd())
    parser.add_argument("--specs", type=Path, default=Path("reference"))
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=Path("skills/asdi-build-conformance"),
    )
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument(
        "auditor",
        nargs=argparse.REMAINDER,
        help="Auditor command executed inside the isolated container.",
    )
    arguments = parser.parse_args()
    report_dir = arguments.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(
        docker=arguments.docker,
        image=arguments.image,
        candidate=arguments.candidate,
        specs=arguments.specs,
        report_dir=report_dir,
        skill_root=arguments.skill_root,
        auditor_command=arguments.auditor,
    )
    invocation_path = report_dir / "invocation.json"
    invocation_path.write_text(
        json.dumps(
            {"argv": command, "shell": shlex.join(command)},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
