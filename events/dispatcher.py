#!/usr/bin/env python3
"""Persist normalized workflow results for every supported journal event."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .main_workflow import MainWorkflowStore
from .pr_workflow import PRWorkflowStore


class EventDispatcher:
    """Route journal events and persist a durable result for each."""

    def __init__(
        self,
        *,
        root: str | Path,
        workflow: PRWorkflowStore | None,
        main_workflow: MainWorkflowStore,
    ) -> None:
        self.root = Path(root).resolve()
        self.workflow = workflow
        self.main_workflow = main_workflow

    def handle(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = event.get("event_type")
        if event_type in {
            "github.push",
            "github.main_verification_completed",
        }:
            result = self.main_workflow.apply(event)
            self._write(
                self.root / "main-workflow-results" / f"event-{event['event_id']}.json",
                result,
            )
            self._write(self.root / "latest-main-workflow.json", result)
            return result
        if event_type in {
            "github.pull_request",
            "github.verification_completed",
            "github.review_completed",
        }:
            if self.workflow is None:
                raise ValueError(
                    "PR event cannot be consumed without a PR workflow; "
                    "poller cursor remains unchanged"
                )
            result = self.workflow.apply(event)
            self._write(
                self.root / "workflow-results" / f"event-{event['event_id']}.json",
                result,
            )
            self._write(self.root / "latest-pr-workflow.json", result)
            packet = result.get("packet")
            if isinstance(packet, dict):
                self._write(self.root / "latest-policy.json", result["gate"])
                self._write(
                    self.root
                    / "packets"
                    / f"pr-{packet['pr_number']}-{packet['head_sha'][:12]}.json",
                    packet,
                )
            return result
        return None

    @staticmethod
    def _write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
