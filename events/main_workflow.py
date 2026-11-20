#!/usr/bin/env python3
"""Durable post-merge state for exact commits on ``main``."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .journal import atomic_json, utc_now
from .pr_gate import deployment_decision, post_merge_check


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
CHECK_STATUSES = {"pass", "fail", "blocked", "error"}


class MainWorkflowStore:
    """Persist ``main`` commits independently of PR-head evidence."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def apply(self, event: dict[str, Any]) -> dict[str, Any]:
        event_type = event.get("event_type")
        if event_type not in {
            "github.push",
            "github.main_verification_completed",
        }:
            return self._reject(event, "unsupported_event_type")
        try:
            event_id = int(event["event_id"])
            if event_id <= 0:
                raise ValueError("event_id must be positive")
        except (KeyError, TypeError, ValueError):
            return self._reject(event, "invalid_event_id")
        if event_type == "github.push":
            return self._apply_push(event, event_id)
        return self._apply_verification(event, event_id)

    def _apply_push(self, event: dict[str, Any], event_id: int) -> dict[str, Any]:
        failures = self._validate_push(event.get("payload"))
        if failures:
            rejection = self._reject(event, "invalid_push_payload", failures)
            return {**rejection, "state": None, "result": None, "deployment": None}
        payload = event["payload"]
        commit = str(payload["commit"])
        current = self.current_state(commit)
        if current is not None:
            return {
                "schema_version": "asdi.main-workflow-result/v1",
                "event_id": event_id,
                "event_type": "github.push",
                "action": "push_replayed",
                "commit": commit,
                "state": current,
                "result": None,
                "deployment": None,
            }
        state = {
            "schema_version": "asdi.main-state/v1",
            "commit": commit,
            "branch": str(payload["branch"]),
            "verification": None,
            "result": None,
            "created_by_event_id": event_id,
            "updated_by_event_id": event_id,
            "updated_at": utc_now(),
        }
        state_path = self._commit_state_path(commit)
        has_prior_main = self._has_prior_main()
        atomic_json(state_path, state)
        atomic_json(self._current_path(), state)
        action = "new_main_commit_recorded" if has_prior_main else "main_commit_recorded"
        return {
            "schema_version": "asdi.main-workflow-result/v1",
            "event_id": event_id,
            "event_type": "github.push",
            "action": action,
            "commit": commit,
            "state": state,
            "state_path": str(state_path),
            "result": None,
            "deployment": None,
        }

    def _apply_verification(
        self,
        event: dict[str, Any],
        event_id: int,
    ) -> dict[str, Any]:
        failures = self._validate_verification(event.get("payload"))
        if failures:
            rejection = self._reject(event, "invalid_verification_payload", failures)
            return {**rejection, "state": None, "result": None, "deployment": None}
        payload = event["payload"]
        commit = str(payload["commit"])
        state = self.current_state(commit)
        if state is None or state.get("schema_version") != "asdi.main-state/v1":
            rejection = self._reject(event, "verification_without_main_commit")
            return {**rejection, "state": None, "result": None, "deployment": None}

        verification = {
            "statuses": dict(payload["statuses"]),
            "verifier": dict(payload["verifier"]),
        }
        if state.get("verification") == verification:
            return {
                "schema_version": "asdi.main-workflow-result/v1",
                "event_id": event_id,
                "event_type": "github.main_verification_completed",
                "action": "verification_replayed",
                "commit": commit,
                "state": state,
                "result": state.get("result"),
                "deployment": deployment_decision(
                    commit=commit,
                    main_results=[state["result"]] if state.get("result") else [],
                ),
            }

        result = post_merge_check(
            {
                "commit": commit,
                "statuses": verification["statuses"],
                "verifier": verification["verifier"],
            }
        )
        updated = {
            **state,
            "verification": verification,
            "result": result,
            "updated_by_event_id": event_id,
            "updated_at": utc_now(),
        }
        state_path = self._commit_state_path(commit)
        result_path = self._result_path(commit)
        atomic_json(state_path, updated)
        atomic_json(self._current_path(), updated)
        atomic_json(result_path, result)
        return {
            "schema_version": "asdi.main-workflow-result/v1",
            "event_id": event_id,
            "event_type": "github.main_verification_completed",
            "action": "verification_recorded",
            "commit": commit,
            "state": updated,
            "state_path": str(state_path),
            "result": result,
            "result_path": str(result_path),
            "deployment": deployment_decision(commit=commit, main_results=[result]),
        }

    def current_state(self, commit: str | None = None) -> dict[str, Any] | None:
        path = (
            self._commit_state_path(str(commit))
            if commit is not None
            else self._current_path()
        )
        if not path.is_file():
            return None
        return json.loads(path.read_text())  # type: ignore[no-any-return]

    def _validate_push(self, value: Any) -> list[str]:
        if not isinstance(value, dict):
            return ["push payload is not an object"]
        failures: list[str] = []
        if value.get("branch") != "main":
            failures.append("only main pushes enter post-merge workflow")
        commit = value.get("commit")
        if not isinstance(commit, str) or not FULL_SHA.fullmatch(commit):
            failures.append("commit must be a 40-character lowercase SHA")
        return failures

    def _validate_verification(self, value: Any) -> list[str]:
        if not isinstance(value, dict):
            return ["verification payload is not an object"]
        failures: list[str] = []
        commit = value.get("commit")
        if not isinstance(commit, str) or not FULL_SHA.fullmatch(commit):
            failures.append("commit must be a 40-character lowercase SHA")
        statuses = value.get("statuses")
        if not isinstance(statuses, dict) or statuses.get("ci") not in CHECK_STATUSES:
            failures.append("statuses must include a ci result")
        verifier = value.get("verifier")
        if not isinstance(verifier, dict):
            failures.append("verifier must be an object")
            return failures
        if verifier.get("candidate_commit") != commit:
            failures.append("verifier is not bound to main commit")
        if verifier.get("status") not in CHECK_STATUSES:
            failures.append("verifier status is invalid")
        if not isinstance(verifier.get("manifest_id"), str) or not verifier["manifest_id"]:
            failures.append("verifier manifest_id is required")
        if not isinstance(verifier.get("run_id"), str) or not verifier["run_id"]:
            failures.append("verifier run_id is required")
        return failures

    def _reject(
        self,
        event: dict[str, Any],
        reason: str,
        failures: list[str] | None = None,
    ) -> dict[str, Any]:
        event_id = event.get("event_id")
        record = {
            "schema_version": "asdi.workflow-rejection/v1",
            "event_id": event_id,
            "event_type": event.get("event_type"),
            "reason": reason,
            "failures": failures or [],
            "event": event,
            "rejected_at": utc_now(),
        }
        result = {
            "schema_version": "asdi.main-workflow-result/v1",
            "event_id": event_id,
            "event_type": event.get("event_type"),
            "action": reason,
            "reason": reason,
            "failures": failures or [],
        }
        if isinstance(event_id, int) and not isinstance(event_id, bool) and event_id > 0:
            path = self.root / "workflow-rejections" / f"event-{event_id}.json"
            atomic_json(path, record)
            result["rejection_path"] = str(path)
        return result

    def _has_prior_main(self) -> bool:
        return (self.root / "main-state").is_dir() and any(
            path.name != "current.json"
            for path in (self.root / "main-state").glob("*.json")
        )

    def _commit_state_path(self, commit: str) -> Path:
        return self.root / "main-state" / f"{commit}.json"

    def _result_path(self, commit: str) -> Path:
        return self.root / "main-results" / f"{commit}.json"

    def _current_path(self) -> Path:
        return self.root / "main-state" / "current.json"
