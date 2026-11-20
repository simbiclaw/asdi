#!/usr/bin/env python3
"""Durable pull-request state across separately arriving GitHub events.

The local journal may see an opened or synchronized PR before its review pass
has completed.  This store therefore keeps a fail-closed pending state by PR
and exact head.  Review evidence is accepted only from an explicitly bound
``github.review_completed`` event; embedded PR-event review data is ignored.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .journal import atomic_json, utc_now
from .pr_gate import PRGate


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
REVIEW_STATUSES = {"pass", "fail", "blocked"}
VERIFIER_STATUSES = {"pass", "fail", "blocked", "error"}


class PRWorkflowStore:
    """Persist and evaluate the event-driven state for one repository."""

    def __init__(
        self,
        root: str | Path,
        *,
        class_config: dict[str, Any],
        feature_map: dict[str, list[str]],
        base_ref: str = "main",
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.class_config = class_config
        self.feature_map = feature_map
        self.base_ref = base_ref

    def apply(self, event: dict[str, Any]) -> dict[str, Any]:
        event_type = event.get("event_type")
        if event_type not in {
            "github.pull_request",
            "github.verification_completed",
            "github.review_completed",
        }:
            return self._reject(event, "unsupported_event_type")
        try:
            event_id = int(event["event_id"])
            if event_id <= 0:
                raise ValueError("event_id must be positive")
        except (KeyError, TypeError, ValueError):
            return self._reject(event, "invalid_event_id")

        if event_type == "github.pull_request":
            return self._apply_pull_request(event, event_id)
        if event_type == "github.verification_completed":
            return self._apply_verification(event, event_id)
        return self._apply_review(event, event_id)

    def _apply_pull_request(
        self,
        event: dict[str, Any],
        event_id: int,
    ) -> dict[str, Any]:
        failures = self._validate_pull_request_payload(event.get("payload"))
        if failures:
            rejection = self._reject(
                event,
                "invalid_pull_request_payload",
                failures,
            )
            return {**rejection, "state": None, "gate": None, "packet": None}

        payload = event["payload"]
        pr_number = int(payload["pr_number"])
        head_sha = str(payload["head_sha"])
        current = self.current_state(pr_number)
        if current is not None and current.get("head_sha") == head_sha:
            return {
                "schema_version": "asdi.pr-workflow-result/v1",
                "event_id": event_id,
                "event_type": "github.pull_request",
                "action": "pull_request_replayed",
                "pr_number": pr_number,
                "head_sha": head_sha,
                "state": current,
                "gate": None,
                "packet": None,
            }

        state = {
            "schema_version": "asdi.pr-state/v1",
            "pr_number": pr_number,
            "head_sha": head_sha,
            "base_ref": str(payload["base_ref"]),
            "changed_paths": list(payload["changed_paths"]),
            "statuses": dict(payload.get("statuses", {})),
            "verifier": payload.get("verifier"),
            "review": None,
            "gate_decision": (
                "pending_review"
                if payload.get("verifier") is not None
                else "pending_verification"
            ),
            "gate_failures": None,
            "created_by_event_id": event_id,
            "updated_by_event_id": event_id,
            "updated_at": utc_now(),
        }
        previous_action = "new_head_recorded" if current is not None else "pull_request_recorded"
        state_path = self._head_state_path(pr_number, head_sha)
        atomic_json(state_path, state)
        atomic_json(self._current_path(pr_number), state)
        return {
            "schema_version": "asdi.pr-workflow-result/v1",
            "event_id": event_id,
            "event_type": "github.pull_request",
            "action": previous_action,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "state": state,
            "state_path": str(state_path),
            "gate": None,
            "packet": None,
        }

    def _apply_review(
        self,
        event: dict[str, Any],
        event_id: int,
    ) -> dict[str, Any]:
        failures = self._validate_review_payload(event.get("payload"))
        if failures:
            rejection = self._reject(event, "invalid_review_payload", failures)
            return {**rejection, "state": None, "gate": None, "packet": None}

        payload = event["payload"]
        pr_number = int(payload["pr_number"])
        head_sha = str(payload["head_sha"])
        state = self.current_state(pr_number)
        if state is None or state.get("schema_version") != "asdi.pr-state/v1":
            rejection = self._reject(event, "review_without_pull_request")
            return {**rejection, "state": None, "gate": None, "packet": None}
        if state.get("head_sha") != head_sha or state.get("pr_number") != pr_number:
            rejection = self._reject(
                event,
                "review_is_not_bound_to_current_head",
            )
            return {**rejection, "state": state, "gate": None, "packet": None}

        review = dict(payload["review"])
        if state.get("review") == review:
            return {
                "schema_version": "asdi.pr-workflow-result/v1",
                "event_id": event_id,
                "event_type": "github.review_completed",
                "action": "review_replayed",
                "pr_number": pr_number,
                "head_sha": head_sha,
                "state": state,
                "gate": None,
                "packet": None,
            }

        updated_state = {
            **state,
            "review": review,
            "updated_by_event_id": event_id,
            "updated_at": utc_now(),
        }
        state_path = self._head_state_path(pr_number, head_sha)
        if updated_state.get("verifier") is None:
            updated_state.update(
                {
                    "gate_decision": "pending_verification",
                    "gate_failures": None,
                }
            )
            atomic_json(state_path, updated_state)
            atomic_json(self._current_path(pr_number), updated_state)
            return {
                "schema_version": "asdi.pr-workflow-result/v1",
                "event_id": event_id,
                "event_type": "github.review_completed",
                "action": "review_recorded_pending_verification",
                "pr_number": pr_number,
                "head_sha": head_sha,
                "state": updated_state,
                "state_path": str(state_path),
                "gate": None,
                "packet": None,
            }
        gate, packet = self._evaluate_gate(updated_state)
        updated_state.update(
            {
                "gate_decision": gate["decision"],
                "gate_failures": gate["failures"],
            }
        )

        packet_path = self._packet_path(pr_number, head_sha)
        atomic_json(state_path, updated_state)
        atomic_json(self._current_path(pr_number), updated_state)
        atomic_json(packet_path, packet)
        return {
            "schema_version": "asdi.pr-workflow-result/v1",
            "event_id": event_id,
            "event_type": "github.review_completed",
            "action": "review_recorded",
            "pr_number": pr_number,
            "head_sha": head_sha,
            "state": updated_state,
            "state_path": str(state_path),
            "gate": gate,
            "packet": packet,
            "packet_path": str(packet_path),
        }

    def _apply_verification(
        self,
        event: dict[str, Any],
        event_id: int,
    ) -> dict[str, Any]:
        failures = self._validate_verification_payload(event.get("payload"))
        if failures:
            rejection = self._reject(event, "invalid_verification_payload", failures)
            return {**rejection, "state": None, "gate": None, "packet": None}

        payload = event["payload"]
        pr_number = int(payload["pr_number"])
        head_sha = str(payload["head_sha"])
        state = self.current_state(pr_number)
        if state is None or state.get("schema_version") != "asdi.pr-state/v1":
            rejection = self._reject(event, "verification_without_pull_request")
            return {**rejection, "state": None, "gate": None, "packet": None}
        if state.get("head_sha") != head_sha or state.get("pr_number") != pr_number:
            rejection = self._reject(
                event,
                "verification_is_not_bound_to_current_head",
            )
            return {**rejection, "state": state, "gate": None, "packet": None}

        verifier = dict(payload["verifier"])
        if state.get("verifier") == verifier and state.get("statuses") == payload["statuses"]:
            return {
                "schema_version": "asdi.pr-workflow-result/v1",
                "event_id": event_id,
                "event_type": "github.verification_completed",
                "action": "verification_replayed",
                "pr_number": pr_number,
                "head_sha": head_sha,
                "state": state,
                "gate": None,
                "packet": None,
            }

        updated_state = {
            **state,
            "statuses": dict(payload["statuses"]),
            "verifier": verifier,
            "updated_by_event_id": event_id,
            "updated_at": utc_now(),
        }
        if state.get("review") is None:
            updated_state.update(
                {
                    "gate_decision": "pending_review",
                    "gate_failures": None,
                }
            )
            state_path = self._head_state_path(pr_number, head_sha)
            atomic_json(state_path, updated_state)
            atomic_json(self._current_path(pr_number), updated_state)
            return {
                "schema_version": "asdi.pr-workflow-result/v1",
                "event_id": event_id,
                "event_type": "github.verification_completed",
                "action": "verification_recorded",
                "pr_number": pr_number,
                "head_sha": head_sha,
                "state": updated_state,
                "state_path": str(state_path),
                "gate": None,
                "packet": None,
            }

        gate, packet = self._evaluate_gate(updated_state)
        updated_state.update(
            {
                "gate_decision": gate["decision"],
                "gate_failures": gate["failures"],
            }
        )
        state_path = self._head_state_path(pr_number, head_sha)
        packet_path = self._packet_path(pr_number, head_sha)
        atomic_json(state_path, updated_state)
        atomic_json(self._current_path(pr_number), updated_state)
        atomic_json(packet_path, packet)
        return {
            "schema_version": "asdi.pr-workflow-result/v1",
            "event_id": event_id,
            "event_type": "github.verification_completed",
            "action": "verification_recorded",
            "pr_number": pr_number,
            "head_sha": head_sha,
            "state": updated_state,
            "state_path": str(state_path),
            "gate": gate,
            "packet": packet,
            "packet_path": str(packet_path),
        }

    def _evaluate_gate(self, state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        gate = PRGate(
            class_config=self.class_config,
            feature_map=self.feature_map,
            base_ref=self.base_ref,
        ).evaluate(
            {
                "pr_number": state["pr_number"],
                "head_sha": state["head_sha"],
                "base_ref": state["base_ref"],
                "changed_paths": state["changed_paths"],
                "statuses": state["statuses"],
                "verifier": state["verifier"],
                "review": state["review"],
            }
        )
        return gate, gate["packet"]

    def current_state(self, pr_number: int) -> dict[str, Any] | None:
        path = self._current_path(int(pr_number))
        if not path.is_file():
            return None
        return json.loads(path.read_text())  # type: ignore[no-any-return]

    def packet(self, pr_number: int, head_sha: str) -> dict[str, Any]:
        """Load the separately persisted packet for one exact PR head."""

        path = self._packet_path(int(pr_number), str(head_sha))
        if not path.is_file():
            raise FileNotFoundError(f"PR packet not found: {path}")
        return json.loads(path.read_text())  # type: ignore[no-any-return]

    def packet_path(self, pr_number: int, head_sha: str) -> Path:
        """Return the durable packet path for one exact PR head."""

        return self._packet_path(int(pr_number), str(head_sha))

    def save_packet(self, pr_number: int, head_sha: str, packet: dict[str, Any]) -> Path:
        """Persist an updated packet after post-gate policy enrichment."""

        path = self._packet_path(int(pr_number), str(head_sha))
        atomic_json(path, packet)
        return path

    def _validate_pull_request_payload(self, value: Any) -> list[str]:
        if not isinstance(value, dict):
            return ["pull request payload is not an object"]
        failures: list[str] = []
        pr_number = value.get("pr_number")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            failures.append("pr_number must be a positive integer")
        head_sha = value.get("head_sha")
        if not isinstance(head_sha, str) or not FULL_SHA.fullmatch(head_sha):
            failures.append("head_sha must be a 40-character lowercase SHA")
        if not isinstance(value.get("base_ref"), str) or not value["base_ref"]:
            failures.append("base_ref must be a non-empty string")
        paths = value.get("changed_paths")
        if (
            not isinstance(paths, list)
            or not paths
            or any(not isinstance(path, str) or not path for path in paths)
        ):
            failures.append("changed_paths must be a non-empty string array")
        statuses = value.get("statuses")
        verifier = value.get("verifier")
        if verifier is not None and not isinstance(verifier, dict):
            failures.append("verifier must be an object when present")
        return failures

    def _validate_verification_payload(self, value: Any) -> list[str]:
        if not isinstance(value, dict):
            return ["verification payload is not an object"]
        failures: list[str] = []
        pr_number = value.get("pr_number")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            failures.append("pr_number must be a positive integer")
        head_sha = value.get("head_sha")
        if not isinstance(head_sha, str) or not FULL_SHA.fullmatch(head_sha):
            failures.append("head_sha must be a 40-character lowercase SHA")
        statuses = value.get("statuses")
        if not isinstance(statuses, dict) or statuses.get("ci") not in {
            "pass",
            "fail",
            "blocked",
            "error",
        }:
            failures.append("statuses must include a ci result")
        if isinstance(statuses, dict) and "asdi/policy" in statuses:
            failures.append("asdi/policy is an output and may not be an input")
        verifier = value.get("verifier")
        if not isinstance(verifier, dict):
            failures.append("verifier must be an object")
            return failures
        if verifier.get("candidate_commit") != head_sha:
            failures.append("verifier is not bound to head_sha")
        if verifier.get("status") not in VERIFIER_STATUSES:
            failures.append("verifier status is invalid")
        if not isinstance(verifier.get("manifest_id"), str) or not verifier["manifest_id"]:
            failures.append("verifier manifest_id is required")
        if not isinstance(verifier.get("run_id"), str) or not verifier["run_id"]:
            failures.append("verifier run_id is required")
        return failures

    def _validate_review_payload(self, value: Any) -> list[str]:
        if not isinstance(value, dict):
            return ["review payload is not an object"]
        failures: list[str] = []
        pr_number = value.get("pr_number")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            failures.append("pr_number must be a positive integer")
        head_sha = value.get("head_sha")
        if not isinstance(head_sha, str) or not FULL_SHA.fullmatch(head_sha):
            failures.append("head_sha must be a 40-character lowercase SHA")
        review = value.get("review")
        if not isinstance(review, dict):
            failures.append("review must be an object")
            return failures
        reviewed_commit = review.get("reviewed_commit")
        if reviewed_commit != head_sha:
            failures.append("review is not bound to head_sha")
        review_status = review.get("status")
        if review_status not in REVIEW_STATUSES:
            failures.append("review status must be pass, fail or blocked")
        passed = review.get("passed")
        if not isinstance(passed, bool):
            failures.append("review passed must be boolean")
        elif isinstance(review_status, str) and passed != (review_status == "pass"):
            failures.append("review passed and status disagree")
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
        path = None
        if isinstance(event_id, int) and not isinstance(event_id, bool) and event_id > 0:
            path = self.root / "workflow-rejections" / f"event-{event_id}.json"
            atomic_json(path, record)
        result = {
            "schema_version": "asdi.pr-workflow-result/v1",
            "event_id": event_id,
            "event_type": event.get("event_type"),
            "action": reason,
            "reason": reason,
            "failures": failures or [],
            "state": None,
            "gate": None,
            "packet": None,
        }
        if path is not None:
            result["rejection_path"] = str(path)
        return result

    def _head_state_path(self, pr_number: int, head_sha: str) -> Path:
        return self.root / "pr-state" / f"pr-{pr_number}" / f"{head_sha}.json"

    def _packet_path(self, pr_number: int, head_sha: str) -> Path:
        return self.root / "packets" / f"pr-{pr_number}" / f"{head_sha}.json"

    def _current_path(self, pr_number: int) -> Path:
        return self.root / "pr-state" / f"pr-{pr_number}" / "current.json"


def packet_digest(packet: dict[str, Any]) -> str:
    """Return a stable digest for audit references without duplicating a packet."""

    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
