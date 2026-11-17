#!/usr/bin/env python3
"""Operate the REV K remediation/specification escalation controller."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from launcher.remediation import RemediationController, RemediationConfig


def split_command(value: str) -> tuple[str, ...]:
    command = tuple(shlex.split(value))
    if not command or not Path(command[0]).is_absolute():
        raise ValueError("command executable must be an absolute path")
    return command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="REV K remediation controller")
    parser.add_argument("--state-root", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    audit = commands.add_parser("audit", help="Run initial independent conformance audit and remediation workflow")
    audit.add_argument("--requirement-id", required=True)
    audit.add_argument("--repo-root", required=True)
    audit.add_argument("--base-revision", default="main")
    audit.add_argument("--phase", default="Pass 1 / Phase 1")
    audit.add_argument("--scope", required=True)
    audit.add_argument("--builder-command", required=True)
    audit.add_argument("--verifier-command", required=True)
    audit.add_argument("--spec-path", action="append", required=True)
    audit.add_argument("--max-cycles", type=int, default=2, choices=(0, 1, 2))

    resume = commands.add_parser("remediate", help="Resume an existing Loop A workflow")
    status = commands.add_parser("status", help="Show durable remediation state")
    report = commands.add_parser("report", help="Print the Specification Feedback Report")
    decision = commands.add_parser("owner-decision", help="Record explicit human direction")
    decision.add_argument("--owner", required=True)
    decision.add_argument(
        "--decision",
        required=True,
        choices=(
            "confirm_original_requirement",
            "clarify_interpretation",
            "approve_specification_amendment",
            "select_alternative_approach",
            "defer_or_abandon_requirement",
        ),
    )
    decision.add_argument("--direction", required=True)
    decision.add_argument(
        "--approved-specification-amendment",
        action="store_true",
        help="Set only after the authoritative revision process has completed.",
    )
    return parser


def controller_from_audit(arguments, root: Path) -> RemediationController:
    config = RemediationConfig(
        requirement_id=arguments.requirement_id,
        repo_root=Path(arguments.repo_root).resolve(),
        base_revision=arguments.base_revision,
        phase=arguments.phase,
        scope=arguments.scope,
        builder_command=split_command(arguments.builder_command),
        verifier_command=split_command(arguments.verifier_command),
        spec_paths=tuple(arguments.spec_path),
        max_cycles=arguments.max_cycles,
    )
    return RemediationController(root, config)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    root = Path(arguments.state_root).resolve()
    try:
        if arguments.command == "audit":
            controller = controller_from_audit(arguments, root)
        else:
            controller = RemediationController.from_state(root)

        if arguments.command == "audit":
            result = controller.audit()
        elif arguments.command == "remediate":
            result = controller.remediate()
        elif arguments.command == "status":
            result = controller.state
        elif arguments.command == "report":
            result = {"report": (root / "spec-feedback-report.md").read_text()}
        elif arguments.command == "owner-decision":
            result = controller.record_owner_decision(
                owner=arguments.owner,
                decision=arguments.decision,
                direction=arguments.direction,
                approved_specification_amendment=arguments.approved_specification_amendment,
            )
        else:
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, indent=2, sort_keys=True))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
