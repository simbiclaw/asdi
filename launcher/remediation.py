#!/usr/bin/env python3
"""REV K implementation remediation and specification-escalation controller.

Loop A allows at most two fresh builder remediation/re-verification cycles after
an initial failed conformance audit.  Loop B stops affected work immediately on
credible evidence of a specification defect and emits a human feedback report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MAX_REMEDIATION_CYCLES = 2
SPEC_SCHEMA_VERSION = "asdi.spec-feedback/v1"
REMEDIATION_SCHEMA_VERSION = "asdi.remediation/v1"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def file_hashes(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(paths):
        if path.is_file():
            result[path.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value)
    else:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


@dataclass(frozen=True)
class RemediationConfig:
    requirement_id: str
    repo_root: Path
    base_revision: str
    phase: str
    scope: str
    builder_command: tuple[str, ...]
    verifier_command: tuple[str, ...]
    spec_paths: tuple[str, ...]
    max_cycles: int = MAX_REMEDIATION_CYCLES
    builder_timeout_seconds: float = 3600.0
    verifier_timeout_seconds: float = 3600.0


class RemediationController:
    """Durable Loop A controller with fail-closed Loop B escalation."""

    def __init__(self, root: str | Path, config: RemediationConfig) -> None:
        if config.max_cycles > MAX_REMEDIATION_CYCLES:
            raise ValueError(
                f"remediation ceiling cannot exceed {MAX_REMEDIATION_CYCLES} cycles"
            )
        if config.max_cycles < 0:
            raise ValueError("remediation ceiling cannot be negative")
        self.root = Path(root).resolve()
        self.config = config
        self.state_path = self.root / "state.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state = self._load()
        self.state["config"] = self._config_dict()
        self._save()

    @property
    def requirement_id(self) -> str:
        return self.config.requirement_id

    def _load(self) -> dict[str, Any]:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {
            "schema_version": REMEDIATION_SCHEMA_VERSION,
            "requirement_id": self.config.requirement_id,
            "status": "not_started",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "original_audit": None,
            "cycles": [],
            "attempted_remediation_cycles": 0,
            "spec_feedback": None,
            "hold": {"active": False},
            "spec_baseline": self._spec_baseline(),
        }

    def _config_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.config.requirement_id,
            "repo_root": str(self.config.repo_root),
            "base_revision": self.config.base_revision,
            "phase": self.config.phase,
            "scope": self.config.scope,
            "builder_command": [str(item) for item in self.config.builder_command],
            "verifier_command": [str(item) for item in self.config.verifier_command],
            "spec_paths": list(self.config.spec_paths),
            "max_cycles": self.config.max_cycles,
            "builder_timeout_seconds": self.config.builder_timeout_seconds,
            "verifier_timeout_seconds": self.config.verifier_timeout_seconds,
        }

    @classmethod
    def from_state(cls, root: str | Path) -> "RemediationController":
        root_path = Path(root).resolve()
        state_path = root_path / "state.json"
        if not state_path.exists():
            raise ValueError("no remediation state")
        state = json.loads(state_path.read_text())
        config_data = state["config"]
        config = RemediationConfig(
            requirement_id=config_data["requirement_id"],
            repo_root=Path(config_data["repo_root"]),
            base_revision=config_data["base_revision"],
            phase=config_data["phase"],
            scope=config_data["scope"],
            builder_command=tuple(config_data["builder_command"]),
            verifier_command=tuple(config_data["verifier_command"]),
            spec_paths=tuple(config_data["spec_paths"]),
            max_cycles=int(config_data["max_cycles"]),
            builder_timeout_seconds=float(config_data["builder_timeout_seconds"]),
            verifier_timeout_seconds=float(config_data["verifier_timeout_seconds"]),
        )
        controller = cls(root_path, config)
        controller.state = state
        return controller

    def _save(self) -> None:
        self.state["updated_at"] = utc_now()
        atomic_json(self.state_path, self.state)

    def _spec_baseline(self) -> dict[str, str]:
        return file_hashes(
            [self.config.repo_root / path for path in self.config.spec_paths]
        )

    def _spec_changes(self) -> dict[str, Any]:
        current = self._spec_baseline()
        baseline = self.state.get("spec_baseline", {})
        changed = sorted(
            path
            for path in set(current) | set(baseline)
            if current.get(path) != baseline.get(path)
        )
        return {
            "changed": bool(changed),
            "paths": changed,
            "baseline": baseline,
            "current": current,
        }

    def _revision(self) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.config.repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"cannot determine candidate revision: {completed.stderr}")
        return completed.stdout.strip()

    def _dirty(self) -> bool:
        completed = subprocess.run(
            ["git", "-C", str(self.config.repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(completed.stdout.strip())

    def _candidate(self) -> str:
        revision = self._revision()
        dirty = self._dirty()
        if dirty:
            completed = subprocess.run(
                ["git", "-C", str(self.config.repo_root), "write-tree"],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                revision = f"{revision}+worktree:{completed.stdout.strip()}"
        return revision

    def _protect_specs(self) -> dict[str, int]:
        protected: dict[str, int] = {}
        for relative in self.config.spec_paths:
            path = self.config.repo_root / relative
            if path.is_file():
                protected[relative] = path.stat().st_mode & 0o777
                path.chmod(0o444)
        return protected

    def _restore_specs(self, modes: dict[str, int]) -> None:
        for relative, mode in modes.items():
            (self.config.repo_root / relative).chmod(mode)

    def _spec_mode_mutations(self, protected: dict[str, int]) -> list[str]:
        return [
            relative
            for relative in protected
            if (self.config.repo_root / relative).stat().st_mode & 0o777 != 0o444
        ]

    def _run_command(
        self,
        command: tuple[str, ...],
        *,
        cycle: int,
        kind: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        started = time.time()
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
            result = {
                "command": list(command),
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-8000:],
                "stderr": completed.stderr[-8000:],
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            result = {"command": list(command), "exit_code": None, "error": str(error)}
        result.update(
            {
                "kind": kind,
                "cycle": cycle,
                "started_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)
                ),
                "duration_seconds": round(time.time() - started, 3),
            }
        )
        return result

    def _run_verifier(self, *, cycle: int, cycle_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        command = list(self.config.verifier_command)
        for index, token in enumerate(command):
            command[index] = token.format(
                repo=str(self.config.repo_root),
                base=self.config.base_revision,
                head=self._candidate(),
                phase=self.config.phase,
                scope=self.config.scope,
                requirement=self.config.requirement_id,
                cycle=cycle,
                report=str(cycle_root / "conformance-report.json"),
            )
        execution = self._run_command(
            tuple(command),
            cycle=cycle,
            kind="verification",
            timeout_seconds=self.config.verifier_timeout_seconds,
        )
        report_path = cycle_root / "conformance-report.json"
        if not report_path.exists():
            report = {
                "schema_version": "asdi.conformance-report/v1",
                "result": "blocked",
                "independent": True,
                "findings": [
                    {
                        "severity": "P1",
                        "observation": "verification agent did not produce a machine-readable report",
                    }
                ],
                "execution": execution,
            }
            _write(report_path, report)
        else:
            report = load_json(report_path)
            report["execution"] = execution
            _write(report_path, report)
        return report, execution

    def _run_builder(self, *, cycle: int, findings_path: Path) -> dict[str, Any]:
        command = list(self.config.builder_command)
        if len(command) == 1:
            command.append("{cycle}")
        for index, token in enumerate(command):
            command[index] = token.format(
                repo=str(self.config.repo_root),
                cycle=cycle,
                findings=str(findings_path),
                requirement=self.config.requirement_id,
            )
        return self._run_command(
            tuple(command),
            cycle=cycle,
            kind="builder",
            timeout_seconds=self.config.builder_timeout_seconds,
        )

    @staticmethod
    def _has_spec_defect(report: dict[str, Any]) -> tuple[bool, str]:
        feedback = report.get("spec_feedback")
        if isinstance(feedback, dict) and feedback.get("required") is True:
            return True, str(feedback.get("defect", "verification agent reported a specification defect"))
        if report.get("spec_defect") is True:
            return True, str(report.get("spec_defect_reason", "verifier reported a specification defect"))
        blocked = str(report.get("blocked_reason", ""))
        if blocked.startswith("SPEC_"):
            return True, blocked
        for finding in report.get("findings", []):
            if finding.get("spec_defect") is True or finding.get("spec_conflict") is True:
                return True, str(finding.get("observation", "finding reports a specification defect"))
        return False, ""

    @staticmethod
    def _report_passes(report: dict[str, Any]) -> bool:
        return (
            report.get("result") == "pass"
            and report.get("independent") is True
            and not report.get("findings", [])
        )

    def _audit(self, *, cycle: int, cycle_root: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
        cycle_root.mkdir(parents=True, exist_ok=True)
        before = self._spec_changes()
        report, execution = self._run_verifier(cycle=cycle, cycle_root=cycle_root)
        after = self._spec_changes()
        if after["changed"]:
            report["spec_mutation"] = after
            report["result"] = "blocked"
            _write(cycle_root / "conformance-report.json", report)
        return report, execution, cycle_root / "conformance-report.json"

    def _record_cycle(
        self,
        *,
        cycle: int,
        report: dict[str, Any],
        report_path: Path,
        builder_execution: dict[str, Any],
        before_revision: str,
        after_revision: str,
        spec_changes: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "cycle": cycle,
            "before_revision": before_revision,
            "candidate_revision": after_revision,
            "fresh_candidate": before_revision != after_revision,
            "builder_execution": builder_execution,
            "verification_report_path": str(report_path),
            "verification_result": report.get("result"),
            "findings": report.get("findings", []),
            "spec_changes": spec_changes,
        }
        self.state.setdefault("cycles", []).append(record)
        self.state["attempted_remediation_cycles"] = len(self.state["cycles"])
        self._save()
        return record

    def _enter_spec_feedback(
        self,
        *,
        trigger: str,
        report: dict[str, Any] | None,
        report_path: Path | None,
        reason: str,
    ) -> dict[str, Any]:
        now = utc_now()
        spec_changes = self._spec_changes()
        feedback = {
            "schema_version": SPEC_SCHEMA_VERSION,
            "requirement_id": self.config.requirement_id,
            "created_at": now,
            "status": "awaiting_owner_direction",
            "trigger": trigger,
            "reason": reason,
            "spec_revision": "REV K",
            "requirement": self.config.scope,
            "implementation_revision": self._candidate(),
            "implementation_dirty": self._dirty(),
            "verification_report": str(report_path) if report_path else None,
            "verification_result": report.get("result") if report else None,
            "verification_findings": report.get("findings", []) if report else [],
            "remediation_cycles_used": self.state.get("attempted_remediation_cycles", 0),
            "remediation_cycles": self.state.get("cycles", []),
            "suspected_spec_defect": reason,
            "technical_consequences": [
                "affected requirement implementation is held",
                "dependent ASDI work that requires this requirement is held",
            ],
            "alternatives": [
                {
                    "action": "confirm_original_requirement",
                    "advantage": "preserves authoritative intent",
                    "disadvantage": "implementation may remain infeasible without redesign",
                },
                {
                    "action": "clarify_interpretation",
                    "advantage": "avoids changing normative text",
                    "disadvantage": "must be precise enough to remove ambiguity",
                },
                {
                    "action": "approve_specification_amendment",
                    "advantage": "corrects the authoritative baseline",
                    "disadvantage": "requires a new revision, fresh baseline and fresh conformance audit",
                },
                {
                    "action": "select_alternative_approach",
                    "advantage": "can unblock implementation without changing text",
                    "disadvantage": "must still satisfy all other authoritative requirements",
                },
                {
                    "action": "defer_or_abandon_requirement",
                    "advantage": "stops spending on the affected outcome",
                    "disadvantage": "affected outcome is not delivered",
                },
            ],
            "decision_required": (
                "Choose confirm, clarify, approve amendment, select an alternative, "
                "or defer/abandon. Do not resume until explicit owner direction is recorded."
            ),
            "spec_changes_during_remediation": spec_changes,
        }
        hold_report_path = self.root / "spec-feedback-report.md"
        _write(hold_report_path, self._render_feedback(feedback))
        atomic_json(self.root / "spec-feedback.json", feedback)
        self.state["spec_feedback"] = feedback
        self.state["hold"] = {
            "active": True,
            "reason": trigger,
            "report": str(hold_report_path),
            "since": now,
        }
        self.state["status"] = "spec_feedback_hold"
        self._save()
        return feedback

    @staticmethod
    def _render_feedback(feedback: dict[str, Any]) -> str:
        cycles = feedback.get("remediation_cycles", [])
        cycle_lines = []
        for cycle in cycles:
            cycle_lines.append(
                f"- Cycle {cycle.get('cycle')}: candidate `{cycle.get('candidate_revision')}`, "
                f"verification `{cycle.get('verification_result')}`, "
                f"fresh_candidate={cycle.get('fresh_candidate')}"
            )
        if not cycle_lines:
            cycle_lines.append("- No remediation cycles; escalation occurred after the initial audit.")
        alternatives = "\n".join(
            f"- **{item['action']}**: {item['advantage']} / {item['disadvantage']}"
            for item in feedback.get("alternatives", [])
        )
        return f"""# Specification Feedback Report

- Requirement: `{feedback.get('requirement_id')}`
- Date: `{feedback.get('created_at')}`
- Status: **{feedback.get('status')}**
- Trigger: `{feedback.get('trigger')}`

## Required decision

{feedback.get('decision_required')}

## Original requirement and intended outcome

{feedback.get('requirement')}

## Implementation and verification evidence

- Candidate revision: `{feedback.get('implementation_revision')}`
- Dirty working tree: `{feedback.get('implementation_dirty')}`
- Verification result: `{feedback.get('verification_result')}`
- Verification report: `{feedback.get('verification_report')}`

## Remediation evidence

{chr(10).join(cycle_lines)}

## Suspected specification defect

{feedback.get('suspected_spec_defect')}

## Technical consequences

{chr(10).join('- ' + item for item in feedback.get('technical_consequences', []))}

## Alternatives

{alternatives}

## Specification changes observed during remediation

```json
{json.dumps(feedback.get('spec_changes_during_remediation', {}), indent=2, sort_keys=True)}
```
"""

    def enforce_hold(self) -> None:
        if self.state.get("hold", {}).get("active") is True:
            raise RuntimeError(
                "specification feedback hold is active; owner direction is required"
            )

    def audit(self) -> dict[str, Any]:
        self.enforce_hold()
        cycle_root = self.root / "initial-audit"
        before = self._candidate()
        report, _execution, report_path = self._audit(cycle=0, cycle_root=cycle_root)
        self.state["original_audit"] = {
            "candidate_revision": before,
            "result": report.get("result"),
            "report_path": str(report_path),
            "recorded_at": utc_now(),
        }
        self._save()

        defect, defect_reason = self._has_spec_defect(report)
        if defect:
            feedback = self._enter_spec_feedback(
                trigger="specification_defect",
                report=report,
                report_path=report_path,
                reason=defect_reason,
            )
            return {
                "action": "escalated_to_specification_feedback",
                "trigger": "specification_defect",
                "initial_audit": report,
                "feedback": feedback,
            }

        if self._report_passes(report):
            self.state["status"] = "verified"
            self.state["original_audit"]["accepted"] = True
            self._save()
            return {
                "action": "accepted_on_initial_audit",
                "initial_audit": report,
                "status": self.state["status"],
            }

        self.state["status"] = "remediation_required"
        self._save()
        return self.remediate(initial_report=report, initial_report_path=report_path)

    def remediate(
        self,
        *,
        initial_report: dict[str, Any] | None = None,
        initial_report_path: Path | None = None,
    ) -> dict[str, Any]:
        self.enforce_hold()
        if self.state.get("status") == "verified":
            return {"action": "none", "status": "verified"}
        if self.state.get("attempted_remediation_cycles", 0) >= self.config.max_cycles:
            return self.escalate(
                trigger="persistent_failure",
                reason="implementation still failed after two remediation/re-verification cycles",
                report=initial_report,
                report_path=initial_report_path,
            )

        initial_report = initial_report or self.state.get("original_audit") or {}
        initial_report_path = (
            Path(initial_report_path)
            if initial_report_path
            else self.root / "initial-audit" / "conformance-report.json"
        )
        findings_path = self.root / "verification-findings.json"
        _write(findings_path, initial_report.get("findings", []))

        for cycle in range(
            self.state.get("attempted_remediation_cycles", 0) + 1,
            self.config.max_cycles + 1,
        ):
            self.enforce_hold()
            before_revision = self._candidate()
            cycle_root = self.root / f"remediation-cycle-{cycle}"
            protected_modes = self._protect_specs()
            try:
                builder = self._run_builder(cycle=cycle, findings_path=findings_path)
                mode_mutations = self._spec_mode_mutations(protected_modes)
            finally:
                self._restore_specs(protected_modes)
            attempted_spec_paths = [
                relative
                for relative in self.config.spec_paths
                if relative in builder.get("stderr", "")
            ]
            if mode_mutations or (builder.get("exit_code") != 0 and attempted_spec_paths):
                feedback = self._enter_spec_feedback(
                    trigger="specification_mutation_during_builder_remediation",
                    report=initial_report,
                    report_path=initial_report_path,
                    reason=(
                        "builder changed permissions or content of a read-only "
                        "authoritative specification file: " + ", ".join(mode_mutations)
                    ),
                )
                self._record_cycle(
                    cycle=cycle,
                    report={"result": "blocked", "spec_mutation": self._spec_changes()},
                    report_path=cycle_root / "conformance-report.json",
                    builder_execution=builder,
                    before_revision=before_revision,
                    after_revision=self._candidate(),
                    spec_changes=self._spec_changes(),
                )
                return {
                    "action": "escalated_to_specification_feedback",
                    "cycle": cycle,
                    "trigger": "specification_mutation_during_builder_remediation",
                    "feedback": feedback,
                }
            after_revision = self._candidate()
            spec_changes = self._spec_changes()
            if spec_changes["changed"]:
                feedback = self._enter_spec_feedback(
                    trigger="specification_mutation_during_builder_remediation",
                    report=initial_report,
                    report_path=initial_report_path,
                    reason="builder remediation changed an authoritative specification file",
                )
                self._record_cycle(
                    cycle=cycle,
                    report={"result": "blocked", "spec_mutation": spec_changes},
                    report_path=cycle_root / "conformance-report.json",
                    builder_execution=builder,
                    before_revision=before_revision,
                    after_revision=after_revision,
                    spec_changes=spec_changes,
                )
                return {
                    "action": "escalated_to_specification_feedback",
                    "cycle": cycle,
                    "trigger": "specification_mutation_during_builder_remediation",
                    "feedback": feedback,
                }

            report, _execution, report_path = self._audit(
                cycle=cycle, cycle_root=cycle_root
            )
            self._record_cycle(
                cycle=cycle,
                report=report,
                report_path=report_path,
                builder_execution=builder,
                before_revision=before_revision,
                after_revision=after_revision,
                spec_changes=self._spec_changes(),
            )

            defect, defect_reason = self._has_spec_defect(report)
            if defect:
                feedback = self._enter_spec_feedback(
                    trigger="specification_defect",
                    report=report,
                    report_path=report_path,
                    reason=defect_reason,
                )
                return {
                    "action": "escalated_to_specification_feedback",
                    "cycle": cycle,
                    "trigger": "specification_defect",
                    "report": report,
                    "feedback": feedback,
                }

            if self._report_passes(report):
                self.state["status"] = "verified"
                self.state["accepted_revision"] = after_revision
                self._save()
                return {
                    "action": "accepted_after_remediation",
                    "cycle": cycle,
                    "candidate_revision": after_revision,
                    "report": report,
                }

            if cycle >= self.config.max_cycles:
                return self.escalate(
                    trigger="persistent_failure",
                    reason="implementation still failed after two remediation/re-verification cycles",
                    report=report,
                    report_path=report_path,
                )

        return self.escalate(
            trigger="persistent_failure",
            reason="remediation quota exhausted",
            report=initial_report,
            report_path=initial_report_path,
        )

    def escalate(
        self,
        *,
        trigger: str,
        reason: str,
        report: dict[str, Any] | None,
        report_path: Path | None,
    ) -> dict[str, Any]:
        feedback = self._enter_spec_feedback(
            trigger=trigger,
            report=report,
            report_path=report_path,
            reason=reason,
        )
        return {
            "action": "escalated_to_specification_feedback",
            "trigger": trigger,
            "feedback": feedback,
        }

    def record_owner_decision(
        self,
        *,
        owner: str,
        decision: str,
        direction: str,
        approved_specification_amendment: bool = False,
    ) -> dict[str, Any]:
        allowed = {
            "confirm_original_requirement",
            "clarify_interpretation",
            "approve_specification_amendment",
            "select_alternative_approach",
            "defer_or_abandon_requirement",
        }
        if decision not in allowed:
            raise ValueError(f"decision must be one of {sorted(allowed)}")
        feedback = self.state.get("spec_feedback")
        if not feedback or feedback.get("status") != "awaiting_owner_direction":
            raise ValueError("no active specification feedback hold")
        feedback["owner"] = owner
        feedback["owner_decision"] = decision
        feedback["owner_direction"] = direction
        feedback["status"] = "owner_decision_recorded"
        feedback["decided_at"] = utc_now()
        if decision == "approve_specification_amendment" and not approved_specification_amendment:
            raise ValueError(
                "approved_specification_amendment must be true only after the authoritative revision process is complete"
            )
        self.state["spec_feedback"] = feedback
        self.state["hold"] = {
            "active": False,
            "reason": "owner direction recorded",
            "decision": decision,
            "since": utc_now(),
        }
        self.state["status"] = f"owner_{decision}"
        self._save()
        atomic_json(self.root / "owner-decision.json", feedback)
        return feedback
