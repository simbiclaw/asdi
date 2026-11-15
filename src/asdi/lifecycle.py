"""Integrated ASDI lifecycle engine and local product operations.

This is a single-host prototype.  Fixture agents make the company loop runnable
before live model adapters are integrated.  Local git merge still requires an
explicit T0 owner authorization; this module cannot autonomously merge.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROTECTED_PATH_SUFFIXES = (
    "CODEOWNERS",
    ".github/workflows/",
)
FORBIDDEN_ARTIFACT_TOKENS = (
    "BEGIN PRIVATE KEY",
    "AWS_ACCESS_KEY_ID=",
    "DOCKER_HOST=",
)


@dataclass(frozen=True)
class MissionGuardrails:
    """Per-mission limits enforced before and during lifecycle work."""

    max_turns: int = 200
    max_spend_usd: float = 8.0
    wall_clock_seconds: int = 5400

    def __post_init__(self) -> None:
        if self.max_turns <= 0 or self.wall_clock_seconds <= 0 or self.max_spend_usd <= 0:
            raise ValueError("mission guardrails must be positive")

    def as_dict(self) -> dict[str, int | float]:
        return {
            "max_turns": self.max_turns,
            "max_spend_usd": self.max_spend_usd,
            "wall_clock_seconds": self.wall_clock_seconds,
        }

    @classmethod
    def from_value(cls, value: dict[str, Any] | None) -> "MissionGuardrails":
        if isinstance(value, cls):
            return value
        defaults = cls()
        if value is None:
            return defaults
        return cls(
            max_turns=int(value.get("max_turns", defaults.max_turns)),
            max_spend_usd=float(value.get("max_spend_usd", defaults.max_spend_usd)),
            wall_clock_seconds=int(value.get("wall_clock_seconds", defaults.wall_clock_seconds)),
        )


@dataclass(frozen=True)
class CommandAgent:
    """Explicit argv adapter for fixture, local, or live coding-agent CLIs.

    Tokens ``{workspace}``, ``{mission_id}``, ``{objective}``, and ``{variant}``
    are substituted before execution.  No shell is used.
    """

    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = 120
    default_cost_usd: float = 0.0
    env: tuple[tuple[str, str], ...] = ()

    def build(
        self,
        *,
        mission_id: str,
        workspace: Path,
        objective: str,
        variant: str,
    ) -> tuple[list[str], dict[str, str]]:
        values = {
            "workspace": str(workspace),
            "mission_id": mission_id,
            "objective": objective,
            "variant": variant,
        }
        command = [token.format(**values) for token in self.argv]
        if not command or not Path(command[0]).is_absolute():
            raise ValueError("agent command executable must be an absolute path")
        if any(not isinstance(item, str) or any(ord(char) < 32 for char in item) for item in command):
            raise ValueError("agent command arguments must be printable")
        environment = {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": "/tmp",
            "LANG": "C.UTF-8",
            "ASDI_RUN_ID": mission_id,
            "ASDI_SANDBOX_MODE": "local_prototype_workspace",
            **dict(self.env),
        }
        return command, environment


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


@dataclass(frozen=True)
class MergeAuthorization:
    """Explicit T0 authorization for one local prototype merge."""

    approver: str
    decision_reference: str
    authority: str = "T0_human"

    def validated(self) -> dict[str, str]:
        if not self.approver.strip() or not self.decision_reference.strip():
            raise ValueError("merge authorization requires approver and decision reference")
        if self.authority != "T0_human":
            raise ValueError("prototype lifecycle only supports T0 human merge authority")
        return {
            "approver": self.approver.strip(),
            "decision_reference": self.decision_reference.strip(),
            "authority": self.authority,
        }


class LifecycleStore:
    """Durable mission state and append-only lifecycle events."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def mission_root(self, mission_id: str) -> Path:
        if not mission_id.startswith("mission_") or any(c in mission_id for c in "/\\"):
            raise ValueError("invalid mission identity")
        return self.root / "missions" / mission_id

    def create_mission(
        self,
        *,
        objective: str,
        why: str,
        constraints: list[str],
        mission_kind: str,
        parent_mission_id: str | None = None,
        detection_evidence: dict[str, Any] | None = None,
        guardrails: MissionGuardrails | dict[str, Any] | None = None,
        external_reference: str | None = None,
        reset_generation: int = 1,
    ) -> dict[str, Any]:
        if not objective.strip() or not why.strip():
            raise ValueError("objective and why are required")
        mission_id = f"mission_{uuid.uuid4()}"
        mission_root = self.mission_root(mission_id)
        mission_root.mkdir(parents=True)
        (mission_root / "workspace").mkdir()
        guardrail_policy = MissionGuardrails.from_value(guardrails)
        now = utc_now()
        state: dict[str, Any] = {
            "schema_version": "asdi.mission/v0",
            "mission_id": mission_id,
            "created_at": now,
            "created_at_ns": time.time_ns(),
            "updated_at": now,
            "status": "admitted",
            "mission_kind": mission_kind,
            "parent_mission_id": parent_mission_id,
            "external_reference": external_reference.strip() if external_reference else None,
            "reset_generation": max(1, int(reset_generation)),
            "objective": objective.strip(),
            "why": why.strip(),
            "constraints": constraints,
            "brief": self._brief(objective, why, constraints, mission_kind),
            "tasks": [],
            "artifacts": [],
            "findings": [],
            "classification": None,
            "merge": None,
            "repair_attempts": 0,
            "closed": False,
            "guardrails": guardrail_policy.as_dict(),
            "budget": {
                "turns_used": 0,
                "spend_usd": 0.0,
                "wall_clock_started_at": time.time(),
                "wall_clock_seconds_used": 0.0,
            },
        }
        self._save(state)
        self.append_event(mission_id, "mission_admitted", {"objective": objective})
        self.append_event(mission_id, "brief_compiled", state["brief"])
        self.append_event(mission_id, "guardrails_configured", state["guardrails"])
        if parent_mission_id:
            self.append_event(
                mission_id,
                "linked_parent_mission",
                {"parent_mission_id": parent_mission_id, "detection_evidence": detection_evidence or {}},
            )
        if reset_generation > 1:
            self.append_event(
                mission_id,
                "brief_v2_created",
                {"reset_generation": reset_generation, "external_reference": external_reference},
            )
        return state

    def load(self, mission_id: str) -> dict[str, Any]:
        path = self.mission_root(mission_id) / "mission.json"
        return json.loads(path.read_text())

    def _save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = utc_now()
        _write_json(self.mission_root(state["mission_id"]) / "mission.json", state)

    def update(self, mission_id: str, patch: dict[str, Any], event: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = self.load(mission_id)
        state.update(patch)
        self._save(state)
        self.append_event(mission_id, event, payload)
        return state

    def append_event(self, mission_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        mission_root = self.mission_root(mission_id)
        events = mission_root / "events.jsonl"
        mission = self.load(mission_id)
        sequence = len(events.read_text().splitlines()) + 1 if events.exists() else 1
        event = {
            "schema_version": "asdi.lifecycle-event/v0",
            "sequence": sequence,
            "mission_id": mission_id,
            "timestamp": utc_now(),
            "type": event_type,
            "payload": payload,
        }
        with events.open("a") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def events(self, mission_id: str) -> list[dict[str, Any]]:
        path = self.mission_root(mission_id) / "events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def find_by_external_reference(self, external_reference: str) -> list[dict[str, Any]]:
        """Return durable missions for a work item, ordered by creation time."""

        needle = external_reference.strip()
        if not needle:
            raise ValueError("external reference is required")
        missions_root = self.root / "missions"
        matches: list[dict[str, Any]] = []
        if not missions_root.exists():
            return matches
        for mission_root in missions_root.glob("mission_*"):
            mission_path = mission_root / "mission.json"
            if not mission_path.is_file():
                continue
            mission = json.loads(mission_path.read_text())
            if mission.get("external_reference") == needle:
                matches.append(mission)
        return sorted(
            matches,
            key=lambda item: (item.get("created_at_ns", 0), item["created_at"]),
        )

    def list_missions(
        self,
        *,
        status: str | None = None,
        mission_kind: str | None = None,
        external_reference: str | None = None,
    ) -> list[dict[str, Any]]:
        missions_root = self.root / "missions"
        matches: list[dict[str, Any]] = []
        if not missions_root.exists():
            return matches
        for mission_path in missions_root.glob("mission_*/mission.json"):
            mission = json.loads(mission_path.read_text())
            if status and mission.get("status") != status:
                continue
            if mission_kind and mission.get("mission_kind") != mission_kind:
                continue
            if external_reference and mission.get("external_reference") != external_reference:
                continue
            matches.append(mission)
        return sorted(
            matches,
            key=lambda item: (item.get("created_at_ns", 0), item["created_at"]),
        )

    @staticmethod
    def _brief(objective: str, why: str, constraints: list[str], mission_kind: str) -> dict[str, Any]:
        scope = "production defect repair" if mission_kind == "repair" else "local prototype feature"
        return {
            "mission_kind": mission_kind,
            "objective": objective,
            "why": why,
            "scope": scope,
            "success_definition": (
                "triage, repaired artifact, independent checks, merge authorization, deployment, and production verification"
                if mission_kind == "repair"
                else "implemented artifact, independent checks, merge authorization, deployment, exposure, and experiment verdict"
            ),
            "constraints": constraints,
            "default_constraints": [
                "no production secrets",
                "no irreversible operations",
                "no autonomous merge",
                "feature flags default off",
            ],
        }


class MissionEngine:
    """Runs the integrated local lifecycle, with fixture or future live agents."""

    def __init__(self, store: LifecycleStore) -> None:
        self.store = store

    def _check_guardrails(self, mission_id: str) -> dict[str, Any]:
        mission = self.store.load(mission_id)
        budget = mission["budget"]
        guardrails = mission["guardrails"]
        elapsed = max(0.0, time.time() - budget["wall_clock_started_at"])
        budget["wall_clock_seconds_used"] = elapsed
        breaches: list[str] = []
        if budget["turns_used"] >= guardrails["max_turns"]:
            breaches.append("max_turns")
        if budget["spend_usd"] >= float(guardrails["max_spend_usd"]):
            breaches.append("max_spend_usd")
        if elapsed >= guardrails["wall_clock_seconds"]:
            breaches.append("wall_clock_seconds")
        self.store._save(mission)
        if breaches:
            payload = {
                "breaches": breaches,
                "budget": {
                    "turns_used": budget["turns_used"],
                    "spend_usd": budget["spend_usd"],
                    "wall_clock_seconds_used": elapsed,
                },
                "limits": guardrails,
            }
            self.store.update(
                mission_id,
                {"status": "guardrail_exceeded"},
                "guardrail_exceeded",
                payload,
            )
            raise RuntimeError(f"mission guardrail exceeded: {', '.join(breaches)}")
        return mission

    def _remaining_wall_clock(self, mission: dict[str, Any]) -> float:
        budget = mission["budget"]
        elapsed = max(0.0, time.time() - budget["wall_clock_started_at"])
        return max(0.0, float(mission["guardrails"]["wall_clock_seconds"]) - elapsed)

    def _settle_guardrails(self, mission_id: str, *, cost_usd: float = 0.0) -> None:
        mission = self.store.load(mission_id)
        mission["budget"]["spend_usd"] = round(
            mission["budget"]["spend_usd"] + max(0.0, cost_usd), 6
        )
        mission["budget"]["wall_clock_seconds_used"] = max(
            0.0, time.time() - mission["budget"]["wall_clock_started_at"]
        )
        self.store._save(mission)
        breaches: list[str] = []
        budget = mission["budget"]
        if budget["spend_usd"] >= float(mission["guardrails"]["max_spend_usd"]):
            breaches.append("max_spend_usd")
        if budget["wall_clock_seconds_used"] >= mission["guardrails"]["wall_clock_seconds"]:
            breaches.append("wall_clock_seconds")
        if breaches:
            self.store.update(
                mission_id,
                {"status": "guardrail_exceeded"},
                "guardrail_exceeded",
                {"breaches": breaches, "budget": budget},
            )
            raise RuntimeError(f"mission guardrail exceeded: {', '.join(breaches)}")

    def decompose(self, mission_id: str) -> dict[str, Any]:
        mission = self.store.load(mission_id)
        if mission["mission_kind"] == "repair":
            tasks = [
                {"id": "triage", "title": "Triage production detection", "status": "pending"},
                {"id": "repair", "title": "Implement bounded repair", "status": "pending"},
                {"id": "independent_review", "title": "Run scoped fresh-context checks", "status": "pending"},
                {"id": "classification", "title": "Classify change and merge authority", "status": "pending"},
                {"id": "deployment", "title": "Deploy repaired release", "status": "pending"},
                {"id": "verification", "title": "Verify production outcome", "status": "pending"},
            ]
        else:
            tasks = [
                {"id": "implement", "title": "Implement requested artifact", "status": "pending"},
                {"id": "self_verification", "title": "Run self-verification", "status": "pending"},
                {"id": "independent_review", "title": "Run scoped fresh-context checks", "status": "pending"},
                {"id": "classification", "title": "Classify change and merge authority", "status": "pending"},
                {"id": "deployment", "title": "Deploy locally with flag off", "status": "pending"},
                {"id": "experiment", "title": "Controlled exposure and verdict", "status": "pending"},
            ]
        state = self.store.update(
            mission_id,
            {"status": "decomposed", "tasks": tasks},
            "mission_decomposed",
            {"task_ids": [task["id"] for task in tasks]},
        )
        return state

    def _task(self, mission_id: str, task_id: str, status: str, evidence: dict[str, Any]) -> dict[str, Any]:
        mission = self.store.load(mission_id)
        for task in mission["tasks"]:
            if task["id"] == task_id:
                task["status"] = status
                task["evidence"] = evidence
                self.store._save(mission)
                self.store.append_event(mission_id, f"task_{status}", {"task_id": task_id, **evidence})
                return mission
        raise ValueError(f"unknown task: {task_id}")

    def execute_agent(
        self,
        mission_id: str,
        *,
        agent_path: str | Path | None = None,
        variant: str,
        timeout: float = 10,
        agent: CommandAgent | None = None,
    ) -> dict[str, Any]:
        mission = self.store.load(mission_id)
        self._check_guardrails(mission_id)
        workspace = self.store.mission_root(mission_id) / "workspace"
        runner = agent or fixture_agent(agent_path or "")
        command, environment = runner.build(
            mission_id=mission_id,
            workspace=workspace,
            objective=mission["objective"],
            variant=variant,
        )
        remaining = self._remaining_wall_clock(mission)
        execution_timeout = min(timeout, runner.timeout_seconds, remaining)
        if execution_timeout <= 0:
            self.store.update(
                mission_id,
                {"status": "guardrail_exceeded"},
                "guardrail_exceeded",
                {"breaches": ["wall_clock_seconds"]},
            )
            raise RuntimeError("mission wall-clock guardrail exceeded")
        mission["budget"]["turns_used"] += 1
        self.store._save(mission)
        started = utc_now()
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=environment,
                capture_output=True,
                text=True,
                timeout=execution_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            if error.stdout is not None:
                output = error.stdout if isinstance(error.stdout, str) else error.stdout.decode(errors="replace")
                (workspace / "agent.stdout.log").write_text(output)
            if error.stderr is not None:
                errors = error.stderr if isinstance(error.stderr, str) else error.stderr.decode(errors="replace")
                (workspace / "agent.stderr.log").write_text(errors)
            evidence = {
                "exit_code": None,
                "error": str(error),
                "guardrail": "wall_clock_seconds",
            }
            self._task(mission_id, mission["tasks"][0]["id"], "failed", evidence)
            self.store.update(
                mission_id,
                {"status": "guardrail_exceeded"},
                "guardrail_exceeded",
                evidence,
            )
            raise RuntimeError("agent execution exceeded wall-clock guardrail") from error
        except OSError as error:
            evidence = {"exit_code": None, "error": str(error)}
            self._task(mission_id, mission["tasks"][0]["id"], "failed", evidence)
            self.store.update(mission_id, {"status": "execution_failed"}, "execution_failed", evidence)
            raise RuntimeError(f"agent execution failed: {error}") from error
        evidence = {
            "command": command,
            "exit_code": completed.returncode,
            "started_at": started,
            "finished_at": utc_now(),
            "stdout_path": "agent.stdout.log",
            "stderr_path": "agent.stderr.log",
        }
        (workspace / "agent.stdout.log").write_text(completed.stdout)
        (workspace / "agent.stderr.log").write_text(completed.stderr)
        try:
            output = json.loads(completed.stdout)
            usage = output.get("usage", output) if isinstance(output, dict) else {}
            if isinstance(usage, dict) and ("cost_usd" in usage or "usd_cost" in usage):
                reported_cost = usage.get("cost_usd", usage.get("usd_cost", 0.0))
                cost_usd = max(0.0, float(reported_cost)) if reported_cost is not None else 0.0
            else:
                cost_usd = runner.default_cost_usd
        except (json.JSONDecodeError, TypeError, ValueError):
            cost_usd = runner.default_cost_usd
        if completed.returncode != 0:
            self._task(mission_id, mission["tasks"][0]["id"], "failed", evidence)
            self.store.update(mission_id, {"status": "execution_failed"}, "execution_failed", evidence)
            raise RuntimeError("fixture agent returned nonzero")
        self._settle_guardrails(mission_id, cost_usd=cost_usd)
        task_id = "repair" if mission["mission_kind"] == "repair" else "implement"
        self._task(mission_id, task_id, "completed", evidence)
        artifact = {
            "path": "app.py",
            "variant": variant,
            "sha256": _sha256(workspace / "app.py"),
        }
        mission = self.store.load(mission_id)
        mission["artifacts"].append(artifact)
        self.store._save(mission)
        self.store.append_event(mission_id, "artifact_created", artifact)
        self.store.update(mission_id, {"status": "implemented"}, "implementation_complete", artifact)
        return evidence

    def self_verify(self, mission_id: str, *, app_path: str | Path) -> dict[str, Any]:
        workspace = self.store.mission_root(mission_id) / "workspace"
        self._check_guardrails(mission_id)
        mission = self.store.load(mission_id)
        mission["budget"]["turns_used"] += 1
        self.store._save(mission)
        remaining = self._remaining_wall_clock(mission)
        if remaining <= 0:
            self.store.update(
                mission_id,
                {"status": "guardrail_exceeded"},
                "guardrail_exceeded",
                {"breaches": ["wall_clock_seconds"]},
            )
            raise RuntimeError("mission wall-clock guardrail exceeded")
        completed = subprocess.run(
            [sys.executable, str(app_path), "--self-check"],
            cwd=workspace,
            capture_output=True,
            text=True,
                timeout=min(5, remaining),
            check=False,
        )
        evidence = {"exit_code": completed.returncode, "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip()}
        if completed.returncode != 0:
            self.store.update(mission_id, {"status": "self_verification_failed"}, "self_verification_failed", evidence)
            raise RuntimeError("self verification failed")
        task_id = "repair" if self.store.load(mission_id)["mission_kind"] == "repair" else "self_verification"
        self._task(mission_id, task_id, "completed", evidence)
        self.store.update(mission_id, {"status": "self_verified"}, "self_verification_passed", evidence)
        self._settle_guardrails(mission_id)
        return evidence

    def independent_review(self, mission_id: str, *, reviewer_path: str | Path) -> list[dict[str, Any]]:
        workspace = self.store.mission_root(mission_id) / "workspace"
        results: list[dict[str, Any]] = []
        for scope in ("correctness", "security", "acceptance"):
            self._check_guardrails(mission_id)
            mission = self.store.load(mission_id)
            mission["budget"]["turns_used"] += 1
            self.store._save(mission)
            remaining = self._remaining_wall_clock(mission)
            if remaining <= 0:
                self.store.update(
                    mission_id,
                    {"status": "guardrail_exceeded"},
                    "guardrail_exceeded",
                    {"breaches": ["wall_clock_seconds"]},
                )
                raise RuntimeError("mission wall-clock guardrail exceeded")
            completed = subprocess.run(
                [sys.executable, os.path.abspath(reviewer_path), "--workspace", str(workspace), "--scope", scope],
                capture_output=True,
                text=True,
                timeout=min(5, remaining),
                check=False,
            )
            try:
                result = json.loads(completed.stdout)
            except json.JSONDecodeError:
                result = {"scope": scope, "passed": False, "findings": ["reviewer returned invalid JSON"]}
            result["exit_code"] = completed.returncode
            self._settle_guardrails(mission_id)
            results.append(result)
        failed = [result for result in results if not result["passed"]]
        mission = self.store.load(mission_id)
        task_id = "independent_review"
        self._task(mission_id, task_id, "completed" if not failed else "failed", {"results": results})
        if failed:
            self.store.update(
                mission_id,
                {"status": "review_failed", "findings": failed},
                "independent_review_failed",
                {"failed_scopes": [result["scope"] for result in failed]},
            )
        else:
            self.store.update(mission_id, {"status": "independently_reviewed"}, "independent_review_passed", {"results": results})
        return results

    def record_triage(self, mission_id: str, defect: dict[str, Any]) -> dict[str, Any]:
        evidence = {
            "defect_id": defect["defect_id"],
            "severity": defect["severity"],
            "triage_decision": defect["triage_decision"],
            "bounded_attempts": 2,
        }
        self._task(mission_id, "triage", "completed", evidence)
        self.store.append_event(mission_id, "defect_triaged", defect)
        return evidence

    def complete_task(self, mission_id: str, task_id: str, evidence: dict[str, Any], *, status: str | None = None) -> dict[str, Any]:
        self._task(mission_id, task_id, "completed", evidence)
        return self.store.update(
            mission_id,
            {"status": status or self.store.load(mission_id)["status"]},
            f"{task_id}_completed",
            evidence,
        )

    def repair(self, mission_id: str, *, agent_path: str | Path, findings: list[dict[str, Any]]) -> dict[str, Any]:
        self._check_guardrails(mission_id)
        mission = self.store.load(mission_id)
        attempts = mission["repair_attempts"] + 1
        if attempts > 2:
            self.store.update(mission_id, {"status": "reset_required"}, "repair_limit_exceeded", {"attempts": attempts})
            raise RuntimeError("repair limit exceeded; brief-v2 reset required")
        workspace = self.store.mission_root(mission_id) / "workspace"
        findings_path = workspace / "review-findings.json"
        findings_path.write_text(json.dumps(findings, indent=2, sort_keys=True) + "\n")
        runner = fixture_agent(agent_path)
        command, environment = runner.build(
            mission_id=mission_id,
            workspace=workspace,
            objective=self.store.load(mission_id)["objective"],
            variant="repair",
        )
        remaining = self._remaining_wall_clock(self.store.load(mission_id))
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
            timeout=min(10, remaining),
            check=False,
        )
        evidence = {"attempt": attempts, "exit_code": completed.returncode}
        self.store.update(mission_id, {"repair_attempts": attempts}, "repair_attempted", evidence)
        if completed.returncode != 0:
            raise RuntimeError("repair agent failed")
        self.store.update(mission_id, {"status": "repaired"}, "repair_completed", evidence)
        return evidence

    def reset(self, mission_id: str, *, reset_reason: str) -> dict[str, Any]:
        """Create a fresh brief-v2 mission after exhausted bounded repair."""

        previous = self.store.load(mission_id)
        if previous["status"] != "reset_required":
            raise ValueError("reset is allowed only after the repair limit is exceeded")
        reset = self.store.create_mission(
            objective=previous["objective"],
            why=f"Brief-v2 reset after failed repair cycle: {reset_reason}",
            constraints=[
                *(previous.get("constraints", [])),
                "prior attempt failed",
                "fresh execution context",
                "no accumulation of prior workspace state",
            ],
            mission_kind=previous["mission_kind"],
            parent_mission_id=mission_id,
            guardrails=previous.get("guardrails"),
            external_reference=previous.get("external_reference"),
            reset_generation=int(previous.get("reset_generation", 1)) + 1,
        )
        self.store.update(
            mission_id,
            {"status": "reset_created", "closed": True},
            "mission_reset_created",
            {
                "reset_mission_id": reset["mission_id"],
                "reset_reason": reset_reason,
            },
        )
        return reset

    def classify(self, mission_id: str) -> dict[str, Any]:
        mission = self.store.load(mission_id)
        paths = [artifact["path"] for artifact in mission["artifacts"]]
        protected = [path for path in paths if path.endswith(PROTECTED_PATH_SUFFIXES)]
        classification = {
            "change_class": "T0_human" if protected or any(path == "app.py" for path in paths) else "T1_local_prototype",
            "protected_paths": protected,
            "production_access": False,
            "irreversible_actions": False,
            "autonomous_merge_authorized": False,
            "reason": "local prototype artifact; remote production merge remains human-governed",
        }
        task_id = "classification"
        self._task(mission_id, task_id, "completed", classification)
        return self.store.update(mission_id, {"status": "classified", "classification": classification}, "change_classified", classification)

    def merge(self, mission_id: str, *, target_root: str | Path, authorization: MergeAuthorization) -> dict[str, Any]:
        mission = self.store.load(mission_id)
        if mission["status"] not in {"independently_reviewed", "repaired", "classified"}:
            raise ValueError("mission is not ready for merge")
        classification = mission["classification"]
        if not classification or classification["autonomous_merge_authorized"]:
            raise ValueError("invalid merge classification")
        auth = authorization.validated()
        target = Path(target_root).resolve()
        completed = subprocess.run(["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise ValueError("merge target is not a git work tree")
        workspace = self.store.mission_root(mission_id) / "workspace"
        for artifact in mission["artifacts"]:
            source = workspace / artifact["path"]
            if source.exists():
                shutil.copy2(source, target / artifact["path"])
        manifest = workspace / "manifest.json"
        if manifest.exists():
            shutil.copy2(manifest, target / "manifest.json")
        subprocess.run(["git", "-C", str(target), "add", "app.py", "manifest.json"], check=True, capture_output=True, text=True)
        commit_message = f"ASDI local prototype merge: {mission_id}"
        commit = subprocess.run(
            [
                "git",
                "-C",
                str(target),
                "-c",
                "user.name=ASDI T0 Merge",
                "-c",
                "user.email=asdi-t0@invalid",
                "commit",
                "-m",
                commit_message,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode != 0 and "nothing to commit" not in commit.stdout + commit.stderr:
            raise RuntimeError(f"local merge commit failed: {commit.stderr}")
        sha = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        merge_record = {
            **auth,
            "local_commit": sha,
            "remote_merge": False,
            "autonomous_merge": False,
        }
        self._task(mission_id, "classification", "completed", {**classification, "merge": merge_record})
        self.store.update(
            mission_id,
            {"status": "merged", "merge": merge_record},
            "local_merge_authorized",
            merge_record,
        )
        return merge_record


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_agent(agent_path: str | Path) -> CommandAgent:
    """Compatibility adapter for the original deterministic fixture script."""

    return CommandAgent(
        name="fixture",
        argv=(
            sys.executable,
            os.path.abspath(agent_path),
            "--workspace",
            "{workspace}",
            "--mission-id",
            "{mission_id}",
            "--variant",
            "{variant}",
        ),
        timeout_seconds=10,
    )


class ProductOps:
    """Minimal local deployment, flags, traffic, monitoring, and learning."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        (self.root / "releases").mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.flags_path = self.root / "flags.json"
        self.traffic_path = self.root / "traffic.jsonl"
        self.observations_path = self.root / "observations.jsonl"
        self.learning_path = self.root / "learning.jsonl"
        if not self.state_path.exists():
            _write_json(self.state_path, {"current_release": None, "deployments": []})
        if not self.flags_path.exists():
            _write_json(self.flags_path, {"prototype_feature": False})

    def deploy(self, mission_id: str, workspace: str | Path) -> dict[str, Any]:
        workspace_path = Path(workspace)
        app_source = workspace_path / "app.py"
        manifest_source = workspace_path / "manifest.json"
        if not app_source.is_file() or not manifest_source.is_file():
            raise ValueError("deployment requires app.py and manifest.json")
        release_id = f"{mission_id}_{uuid.uuid4().hex[:8]}"
        release_root = self.root / "releases" / release_id
        release_root.mkdir(parents=True)
        shutil.copy2(app_source, release_root / "app.py")
        shutil.copy2(manifest_source, release_root / "manifest.json")
        _write_json(
            release_root / "release.json",
            {"release_id": release_id, "mission_id": mission_id, "deployed_at": utc_now(), "flag_default": False},
        )
        temporary_link = self.root / f".current-{uuid.uuid4().hex}"
        os.symlink(release_root, temporary_link, target_is_directory=True)
        os.replace(temporary_link, self.root / "current")
        state = json.loads(self.state_path.read_text())
        deployment = {
            "release_id": release_id,
            "mission_id": mission_id,
            "deployed_at": utc_now(),
            "rollback_of": state.get("current_release"),
        }
        state["current_release"] = release_id
        state["deployments"].append(deployment)
        _write_json(self.state_path, state)
        self._append(self.learning_path, {"type": "deployment", **deployment})
        return deployment

    def rollback(self, *, reason: str) -> dict[str, Any]:
        state = json.loads(self.state_path.read_text())
        deployments = state["deployments"]
        if len(deployments) < 2:
            raise ValueError("no previous local release to roll back")
        previous = deployments[-2]
        target = self.root / "releases" / previous["release_id"]
        temporary_link = self.root / f".current-{uuid.uuid4().hex}"
        os.symlink(target, temporary_link, target_is_directory=True)
        os.replace(temporary_link, self.root / "current")
        rollback = {"rollback_to": previous["release_id"], "reason": reason, "at": utc_now()}
        state["current_release"] = previous["release_id"]
        state["deployments"].append({"release_id": previous["release_id"], "mission_id": previous["mission_id"], "rollback": rollback})
        _write_json(self.state_path, state)
        self._append(self.learning_path, {"type": "rollback", **rollback})
        return rollback

    def current_app(self) -> Path:
        path = self.root / "current" / "app.py"
        if not path.is_file():
            raise ValueError("no current local release")
        return path

    def set_flag(self, name: str, enabled: bool, *, decision_reference: str) -> dict[str, Any]:
        flags = json.loads(self.flags_path.read_text())
        previous = flags.get(name, False)
        flags[name] = enabled
        _write_json(self.flags_path, flags)
        record = {"flag": name, "previous": previous, "enabled": enabled, "decision_reference": decision_reference, "at": utc_now()}
        self._append(self.learning_path, {"type": "flag_change", **record})
        return record

    def request(self, *, scenario: str = "normal") -> dict[str, Any]:
        flags = json.loads(self.flags_path.read_text())
        completed = subprocess.run(
            [sys.executable, str(self.current_app()), "--handle", "--scenario", scenario, "--flag-enabled", str(flags.get("prototype_feature", False)).lower()],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError:
            response = {"ok": False, "error": completed.stderr.strip() or "invalid product response"}
        record = {"scenario": scenario, "response": response, "exit_code": completed.returncode, "at": utc_now()}
        self._append(self.traffic_path, record)
        return record

    def experiment(self, *, name: str = "prototype_feature", traffic: int = 4) -> dict[str, Any]:
        if not json.loads(self.flags_path.read_text()).get(name):
            raise ValueError("experiment requires controlled exposure")
        outcomes = [self.request(scenario="load" if index == traffic - 1 else "normal") for index in range(traffic)]
        passed = sum(1 for item in outcomes if item["response"].get("ok") is True)
        verdict = "keep_for_human_review" if passed == traffic else "kill_candidate"
        verdict_record = {
            "experiment": name,
            "traffic": traffic,
            "passed": passed,
            "failed": traffic - passed,
            "verdict": verdict,
            "at": utc_now(),
        }
        self._append(self.learning_path, {"type": "experiment_verdict", **verdict_record})
        return {"outcomes": outcomes, **verdict_record}

    def observe(self, *, scenario: str = "load") -> dict[str, Any]:
        result = self.request(scenario=scenario)
        observation = {
            **result,
            "healthy": result["exit_code"] == 0 and result["response"].get("ok") is True,
            "monitor": "local_health_probe",
        }
        self._append(self.observations_path, observation)
        return observation

    def raise_defect(self, observation: dict[str, Any]) -> dict[str, Any]:
        if observation["healthy"]:
            raise ValueError("cannot raise defect from healthy observation")
        defect = {
            "defect_id": f"defect_{uuid.uuid4()}",
            "detected_at": utc_now(),
            "release_id": json.loads(self.state_path.read_text())["current_release"],
            "scenario": observation["scenario"],
            "response": observation["response"],
            "severity": "prototype_sev3",
            "triage_decision": "bounded_autonomous_repair",
            "exposure": "local controlled prototype only",
        }
        self._append(self.learning_path, {"type": "defect_detected", **defect})
        return defect

    def verify_repair(self, *, traffic: int = 4) -> dict[str, Any]:
        outcomes = [self.request(scenario="load" if index == traffic - 1 else "normal") for index in range(traffic)]
        passed = all(item["response"].get("ok") is True and item["exit_code"] == 0 for item in outcomes)
        record = {
            "type": "production_verification",
            "outcomes": outcomes,
            "passed": passed,
            "closure": "closed_verified" if passed else "reopened",
            "at": utc_now(),
        }
        self._append(self.learning_path, record)
        return record

    def close_defect(self, defect: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
        closure = {
            "type": "defect_closure",
            "defect_id": defect["defect_id"],
            "closure": verification["closure"],
            "verified_at": verification["at"],
            "reopened": verification["closure"] == "reopened",
        }
        self._append(self.learning_path, closure)
        return closure

    def _append(self, path: Path, value: dict[str, Any]) -> None:
        with path.open("a") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def ensure_local_target(target_root: str | Path) -> Path:
    target = Path(target_root).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").exists():
        subprocess.run(["git", "init", "--initial-branch", "main", str(target)], check=True, capture_output=True, text=True)
    readme = target / "README.md"
    if not readme.exists():
        readme.write_text("# ASDI local prototype product\n")
        subprocess.run(["git", "-C", str(target), "add", "README.md"], check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "-C", str(target), "-c", "user.name=ASDI Bootstrap", "-c", "user.email=asdi@invalid", "commit", "-m", "bootstrap local prototype"],
            check=True,
            capture_output=True,
            text=True,
        )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect local lifecycle evidence roots")
    parser.add_argument("--root", required=True)
    arguments = parser.parse_args()
    root = Path(arguments.root)
    for name in ("missions", "state.json", "flags.json", "traffic.jsonl", "learning.jsonl"):
        path = root / name
        print(f"{name}: {path.exists()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
