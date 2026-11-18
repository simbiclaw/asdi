"""Task-type TRM governance and paired engineering metrics."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRM_SCHEMA_VERSION = "asdi.trm-ledger/v1"
T0_FIRST_PASS_THRESHOLD = 3
T1_FIRST_PASS_THRESHOLD = 5
T1_STABLE_DAYS = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


class TRMLedger:
    """Durable, evidence-only task-type Task Readiness Maturity ledger."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.state_path = self.root / "trm.json"
        self.events_path = self.root / "trm-events.jsonl"
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {
            "schema_version": TRM_SCHEMA_VERSION,
            "task_types": {},
        }

    def _save(self) -> None:
        _atomic_write(self.state_path, self.state)

    def _task(self, task_type: str) -> dict[str, Any]:
        task_types = self.state.setdefault("task_types", {})
        return task_types.setdefault(
            task_type,
            {
                "maturity": "T0",
                "first_passes_since_promotion": 0,
                "promotion_at": _now_iso(),
                "t1_promoted_at": None,
                "t2_promoted_at": None,
                "reset_streak": 0,
                "demoted_by_model_release": False,
                "pre_release_maturity": None,
                "judgment_path": False,
            },
        )

    def _append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        events = self.events_path.read_text().splitlines() if self.events_path.exists() else []
        record = {
            "sequence": len(events) + 1,
            "recorded_at": _now_iso(),
            **event,
        }
        with self.events_path.open("a") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def _transition(
        self,
        task_type: str,
        new_maturity: str,
        *,
        reason: str,
        evidence: dict[str, Any],
        occurred_at: str,
    ) -> dict[str, Any]:
        task = self._task(task_type)
        old_maturity = task["maturity"]
        task["maturity"] = new_maturity
        task["first_passes_since_promotion"] = 0
        task["promotion_at"] = occurred_at
        if new_maturity == "T1":
            task["t1_promoted_at"] = occurred_at
            task["t2_promoted_at"] = None
        elif new_maturity == "T2":
            task["t2_promoted_at"] = occurred_at
        task["reset_streak"] = 0
        self._save()
        return self._append_event(
            {
                "type": "maturity_transition",
                "task_type": task_type,
                "from": old_maturity,
                "to": new_maturity,
                "reason": reason,
                "evidence": evidence,
                "occurred_at": occurred_at,
            }
        )

    def record_first_pass(
        self,
        *,
        task_type: str,
        mission_id: str,
        evidence: dict[str, Any],
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        occurred = occurred_at or _now_iso()
        occurred_time = _parse_time(occurred)
        task = self._task(task_type)
        if task["maturity"] == "T2":
            task["reset_streak"] = 0
            self._save()
            event = {
                "type": "first_pass_recorded",
                "task_type": task_type,
                "mission_id": mission_id,
                "maturity": task["maturity"],
                "counted_for_promotion": False,
                "evidence": evidence,
                "occurred_at": occurred,
            }
            self._save()
            return self._append_event(event)
        task["first_passes_since_promotion"] += 1
        event = {
            "type": "first_pass_recorded",
            "task_type": task_type,
            "mission_id": mission_id,
            "maturity": task["maturity"],
            "counted_for_promotion": True,
            "count": task["first_passes_since_promotion"],
            "evidence": evidence,
            "occurred_at": occurred,
        }
        transition = None
        if task["maturity"] == "T0":
            if task["first_passes_since_promotion"] >= T0_FIRST_PASS_THRESHOLD:
                transition = self._transition(
                    task_type,
                    "T1",
                    reason=f"three first-pass approvals ({T0_FIRST_PASS_THRESHOLD})",
                    evidence=evidence,
                    occurred_at=occurred,
                )
        elif task["maturity"] == "T1":
            promoted_time = _parse_time(task["t1_promoted_at"])
            stable_seconds = (occurred_time - promoted_time).total_seconds()
            stable_days = stable_seconds / 86400
            if (
                task["first_passes_since_promotion"] >= T1_FIRST_PASS_THRESHOLD
                and stable_days >= T1_STABLE_DAYS
            ):
                transition = self._transition(
                    task_type,
                    "T2",
                    reason="five additional first-pass approvals after 30 stable days",
                    evidence={**evidence, "stable_days": stable_days},
                    occurred_at=occurred,
                )
            else:
                event["stable_days"] = stable_days
                event["promotion_blocked"] = (
                    "thirty_day_stability" if stable_days < T1_STABLE_DAYS else None
                )
        self._save()
        self._append_event(event)
        if transition:
            return self._append_event({**transition, "related_event": True})
        return event

    def record_revert(
        self,
        *,
        task_type: str,
        evidence: dict[str, Any],
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        occurred = occurred_at or _now_iso()
        task = self._task(task_type)
        if task["maturity"] not in {"T1", "T2"}:
            task["reset_streak"] = 0
            self._save()
            return self._append_event(
                {
                    "type": "revert_recorded",
                    "task_type": task_type,
                    "from": task["maturity"],
                    "transition": False,
                    "evidence": evidence,
                    "occurred_at": occurred,
                }
            )
        transition = self._transition(
            task_type,
            "T0",
            reason=f"{task['maturity']} revert",
            evidence=evidence,
            occurred_at=occurred,
        )
        return self._append_event({**transition, "related_event": True})

    def record_escaped_defect(
        self,
        *,
        task_type: str,
        evidence: dict[str, Any],
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        occurred = occurred_at or _now_iso()
        task = self._task(task_type)
        if task["maturity"] != "T2":
            return self._append_event(
                {
                    "type": "escaped_defect_recorded",
                    "task_type": task_type,
                    "from": task["maturity"],
                    "transition": False,
                    "evidence": evidence,
                    "occurred_at": occurred,
                }
            )
        transition = self._transition(
            task_type,
            "T0",
            reason="T2 escaped defect",
            evidence=evidence,
            occurred_at=occurred,
        )
        return self._append_event({**transition, "related_event": True})

    def record_reset(
        self,
        *,
        task_type: str,
        evidence: dict[str, Any],
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        occurred = occurred_at or _now_iso()
        task = self._task(task_type)
        if task["maturity"] != "T2":
            return self._append_event(
                {
                    "type": "reset_recorded",
                    "task_type": task_type,
                    "from": task["maturity"],
                    "transition": False,
                    "evidence": evidence,
                    "occurred_at": occurred,
                }
            )
        task["reset_streak"] += 1
        self._save()
        event = {
            "type": "reset_recorded",
            "task_type": task_type,
            "streak": task["reset_streak"],
            "evidence": evidence,
            "occurred_at": occurred,
        }
        if task["reset_streak"] >= 2:
            transition = self._transition(
                task_type,
                "T1",
                reason="two consecutive resets at T2",
                evidence=evidence,
                occurred_at=occurred,
            )
            return self._append_event({**transition, "related_event": True})
        self._append_event(event)
        return event

    def record_model_release(
        self,
        *,
        release_id: str,
        occurred_at: str | None = None,
    ) -> list[dict[str, Any]]:
        occurred = occurred_at or _now_iso()
        records: list[dict[str, Any]] = []
        for task_type, task in list(self.state.get("task_types", {}).items()):
            if task["maturity"] not in {"T1", "T2"}:
                continue
            task["pre_release_maturity"] = task["maturity"]
            task["demoted_by_model_release"] = True
            self._save()
            transition = self._transition(
                task_type,
                "T1",
                reason="model release requires evaluation",
                evidence={"release_id": release_id},
                occurred_at=occurred,
            )
            records.append(self._append_event({**transition, "related_event": True}))
        if not records:
            records.append(
                self._append_event(
                    {
                        "type": "model_release_recorded",
                        "release_id": release_id,
                        "affected_task_types": [],
                        "occurred_at": occurred,
                    }
                )
            )
        return records

    def record_evaluation_passed(
        self,
        *,
        release_id: str,
        evidence: dict[str, Any],
        occurred_at: str | None = None,
    ) -> list[dict[str, Any]]:
        occurred = occurred_at or _now_iso()
        records: list[dict[str, Any]] = []
        for task_type, task in list(self.state.get("task_types", {}).items()):
            if not task.get("demoted_by_model_release"):
                continue
            restore_to = task.get("pre_release_maturity", "T1")
            task["demoted_by_model_release"] = False
            task["pre_release_maturity"] = None
            self._save()
            transition = self._transition(
                task_type,
                restore_to,
                reason="model-release evaluation passed",
                evidence={"release_id": release_id, **evidence},
                occurred_at=occurred,
            )
            records.append(self._append_event({**transition, "related_event": True}))
        return records

    def mark_judgment_path(self, *, task_type: str) -> dict[str, Any]:
        task = self._task(task_type)
        task["judgment_path"] = True
        self._save()
        return self._append_event(
            {
                "type": "judgment_path_marked",
                "task_type": task_type,
                "effective_supervision": self.effective_maturity(task_type),
            }
        )

    def effective_maturity(self, task_type: str) -> str:
        task = self._task(task_type)
        if task.get("judgment_path") and task["maturity"] == "T2":
            return "T1"
        return task["maturity"]

    def snapshot(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for task_type in self.state.get("task_types", {}):
            task = self._task(task_type)
            result[task_type] = {
                **task,
                "effective_maturity": self.effective_maturity(task_type),
            }
        return {
            "schema_version": TRM_SCHEMA_VERSION,
            "task_types": result,
        }

    def events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        return [json.loads(line) for line in self.events_path.read_text().splitlines()]


def paired_metrics(company_root: str | Path, *, window_days: int = 7) -> dict[str, Any]:
    """Compute required speed metrics with their mandatory countermeasures."""

    root = Path(company_root)
    product_root = root / "product"
    learning = []
    learning_path = product_root / "learning.jsonl"
    if learning_path.exists():
        learning = [json.loads(line) for line in learning_path.read_text().splitlines()]

    missions: list[dict[str, Any]] = []
    missions_root = root / "missions"
    if missions_root.exists():
        missions = [
            json.loads(path.read_text())
            for path in missions_root.glob("mission_*/mission.json")
        ]

    deployments = [event for event in learning if event.get("type") == "deployment"]
    rollbacks = [event for event in learning if event.get("type") == "rollback"]
    incidents = [event for event in learning if event.get("type") == "defect_detected"]
    verdicts = [event for event in learning if event.get("type") == "experiment_verdict"]
    closures = [event for event in learning if event.get("type") == "defect_closure"]
    reopened = [event for event in closures if event.get("reopened") is True]
    local_merges = [
        mission
        for mission in missions
        if isinstance(mission.get("merge"), dict) and mission["merge"].get("local_commit")
    ]
    bot_merges = [
        mission for mission in local_merges if mission["merge"].get("autonomous_merge") is True
    ]
    reset_created = [
        event
        for mission in missions
        for event in [
            json.loads(line)
            for line in (
                (missions_root / mission["mission_id"] / "events.jsonl").read_text().splitlines()
                if (missions_root / mission["mission_id"] / "events.jsonl").exists()
                else []
            )
        ]
        if event.get("type") == "mission_reset_created"
    ]
    successful_resets = [
        mission
        for mission in missions
        if int(mission.get("reset_generation", 1)) > 1
        and mission.get("status") in {"experiment_completed", "production_verified"}
    ]
    flags_path = product_root / "flags.json"
    flags = json.loads(flags_path.read_text()) if flags_path.exists() else {}

    first_passes = TRMLedger(root / "governance").events()
    first_pass_count = sum(
        1 for event in first_passes if event.get("type") == "first_pass_recorded"
    )
    review_pass_runs = sum(
        1
        for mission in missions
        for event in [
            json.loads(line)
            for line in (
                (missions_root / mission["mission_id"] / "events.jsonl").read_text().splitlines()
                if (missions_root / mission["mission_id"] / "events.jsonl").exists()
                else []
            )
        ]
        if event.get("type") == "independent_review_passed"
    )

    def metric(value: Any, source: str, countermeasure: str) -> dict[str, Any]:
        return {
            "value": value,
            "source": source,
            "countermeasure": countermeasure,
        }

    return {
        "window_days": window_days,
        "provenance": {
            "missions": len(missions),
            "learning_events": len(learning),
            "trm_events": len(first_passes),
            "generated_at": _now_iso(),
        },
        "metrics": {
            "pr_cycle_time": metric(
                None,
                "not_available:no_pull_request_data_in_local_prototype",
                "revert_rate",
            ),
            "share_of_merges_by_bot": metric(
                len(bot_merges) / len(local_merges) if local_merges else 0.0,
                "missions_with_local_merge",
                "bot_merge_revert_rate_and_misroute_sampling",
            ),
            "deploys_per_day": metric(
                len(deployments) / max(1, window_days),
                "learning.deployment_events",
                "rollback_rate_and_post_deploy_incidents",
            ),
            "experiments_decided_per_week": metric(
                len(verdicts) / max(1, window_days),
                "learning.experiment_verdict_events",
                "expired_flags_and_total_flags",
            ),
            "detection_to_verified_fix": metric(
                None,
                "not_available:no_paired_duration_fields_in_local_defect_ledger",
                "reopen_rate",
            ),
            "first_pass_approval_rate": metric(
                first_pass_count / review_pass_runs if review_pass_runs else None,
                "trm_first_pass_events_over_lifecycle_independent_review_passes",
                "escaped_defects_and_one_in_ten_deep_review",
            ),
            "resets_per_run": metric(
                len(reset_created) / len(missions) if missions else 0.0,
                "lifecycle.mission_reset_created_events",
                "brief_v2_success_rate",
            ),
            "rule_count": metric(
                0,
                "not_available:no_rule_ledger_yet",
                "recurrence_of_same_correction",
            ),
        },
        "countermeasures": {
            "revert_rate": len(rollbacks) / len(deployments) if deployments else 0.0,
            "bot_merge_revert_rate": len(rollbacks) / len(bot_merges) if bot_merges else 0.0,
            "post_deploy_incidents": len(incidents),
            "expired_flags": 0,
            "total_flags": len(flags),
            "reopen_rate": len(reopened) / len(closures) if closures else 0.0,
            "escaped_defects": len(incidents),
            "brief_v2_success_rate": (
                len(successful_resets) / len(reset_created) if reset_created else None
            ),
            "recurrence_of_same_correction": None,
        },
    }
