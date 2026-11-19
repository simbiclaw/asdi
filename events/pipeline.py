#!/usr/bin/env python3
"""Operational PR-gate pipeline over durable events and explicit commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .dispatcher import EventDispatcher
from .journal import EventJournal, LocalPoller, PollerState, atomic_json
from .main_workflow import MainWorkflowStore
from .merge_gate import evaluate_merge_packet
from .pr_workflow import PRWorkflowStore
from .review import ReviewCommand, review_event_payload, run_review
from .verification import verification_event_payload


def run_pr_gate_pipeline(
    *,
    root: str | Path,
    journal: EventJournal,
    poller_state: PollerState,
    workflow: PRWorkflowStore,
    main_workflow: MainWorkflowStore,
    pr_number: int,
    evidence: dict[str, Any],
    ci_status: str,
    diff: str,
    reviewer: ReviewCommand,
    actor: str,
    trm_level: str,
    review_result_path: str | Path,
) -> dict[str, Any]:
    """Verify, review, evaluate and dry-run one current PR without merging.

    Verification must already exist as a launcher-produced evidence manifest.
    The pipeline maps it into a durable event, executes an explicit fresh
    reviewer, persists the full review result separately, appends only its
    normalized verdict, and performs the existing fail-closed merge dry run.
    """

    root_path = Path(root).resolve()
    state = workflow.current_state(pr_number)
    if state is None or state.get("schema_version") != "asdi.pr-state/v1":
        raise ValueError(f"PR {pr_number} has no durable workflow state")
    head_sha = state.get("head_sha")
    if not isinstance(head_sha, str) or not head_sha:
        raise ValueError(f"PR {pr_number} has no durable head")

    appended_events: list[dict[str, Any]] = []
    if state.get("verifier") is None:
        verification_payload = verification_event_payload(
            packet={"pr_number": pr_number, "head_sha": head_sha},
            evidence=evidence,
            ci_status=ci_status,
        )
        appended_events.append(
            journal.append(
                event_type="github.verification_completed",
                payload=verification_payload,
            )
        )

    # Reload after verification because a replay may already contain evidence.
    state = workflow.current_state(pr_number) or {}
    if state.get("review") is None:
        review_packet = {
            "pr_number": pr_number,
            "head_sha": head_sha,
            "changed_paths": state.get("changed_paths", []),
        }
        review_result = run_review(
            packet=review_packet,
            diff=diff,
            command=reviewer,
        )
        destination = Path(review_result_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(destination, review_result)
        appended_events.append(
            journal.append(
                event_type="github.review_completed",
                payload=review_event_payload(packet=review_packet, result=review_result),
            )
        )

    dispatcher = EventDispatcher(
        root=root_path,
        workflow=workflow,
        main_workflow=main_workflow,
    )
    catch_up = LocalPoller(journal=journal, state=poller_state).catch_up(
        handler=dispatcher.handle,
    )
    final_state = workflow.current_state(pr_number) or {}
    if (
        final_state.get("verifier") is None
        or final_state.get("review") is None
    ):
        raise ValueError("PR pipeline did not produce both verifier and review evidence")
    packet = workflow.packet(pr_number, head_sha)
    merge = evaluate_merge_packet(
        packet,
        actor=actor,
        trm_level=trm_level,
    )
    result = {
        "schema_version": "asdi.pr-gate-pipeline/v1",
        "pr_number": pr_number,
        "head_sha": head_sha,
        "policy": final_state.get("gate_decision"),
        "packet": packet,
        "merge_dry_run": merge,
        "merge_executed": False,
        "appended_event_ids": [event["event_id"] for event in appended_events],
        "catch_up": catch_up,
        "review_result_path": str(Path(review_result_path).resolve()),
    }
    atomic_json(root_path / "latest-pr-gate-pipeline.json", result)
    atomic_json(root_path / "latest-merge-dry-run.json", merge)
    return result
