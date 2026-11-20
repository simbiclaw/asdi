#!/usr/bin/env python3
"""Operational exact-main verification pipeline over explicit commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .dispatcher import EventDispatcher
from .journal import EventJournal, LocalPoller, PollerState, atomic_json
from .main_workflow import MainWorkflowStore
from .pr_gate import deployment_decision
from .verifier_command import (
    VerificationCommand,
    run_verification,
    verification_execution_event_payload,
)


def run_main_verification_pipeline(
    *,
    root: str | Path,
    journal: EventJournal,
    poller_state: PollerState,
    main_workflow: MainWorkflowStore,
    verification_command: VerificationCommand,
    ci_status: str,
    verification_result_path: str | Path,
    commit: str | None = None,
) -> dict[str, Any]:
    """Verify the current exact ``main`` commit without deploying.

    The command must produce a launcher verifier-only result bound to the
    exact landed commit with source ``main``.  The pipeline appends only
    normalized post-merge evidence; complete execution output remains in the
    separately persisted result.  Existing verification is replayed without
    invoking the verifier again.
    """

    root_path = Path(root).resolve()
    if verification_command.source != "main":
        raise ValueError("main verification requires a verifier command with source main")
    state = main_workflow.current_state(commit)
    if state is None or state.get("schema_version") != "asdi.main-state/v1":
        raise ValueError("requested commit has no durable main workflow state")
    landed_commit = state.get("commit")
    if state.get("branch") != "main" or not isinstance(landed_commit, str):
        raise ValueError("main workflow state is not bound to branch main")

    execution_result_path = Path(verification_result_path).resolve()
    appended_events: list[dict[str, Any]] = []
    verification_result: dict[str, Any] | None = None
    action = "verification_already_recorded"
    if state.get("verification") is None:
        verification_result = run_verification(
            command=verification_command,
            head_sha=landed_commit,
        )
        execution_result_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(execution_result_path, verification_result)
        payload = verification_execution_event_payload(
            packet={"head_sha": landed_commit},
            result=verification_result,
            ci_status=ci_status,
        )
        appended_events.append(
            journal.append(
                event_type="github.main_verification_completed",
                payload=payload,
            )
        )
        action = "verification_executed"

    dispatcher = EventDispatcher(
        root=root_path,
        workflow=None,
        main_workflow=main_workflow,
    )
    catch_up = LocalPoller(journal=journal, state=poller_state).catch_up(
        handler=dispatcher.handle,
    )
    final_state = main_workflow.current_state(landed_commit) or {}
    result = final_state.get("result")
    deployment = (
        deployment_decision(commit=landed_commit, main_results=[result])
        if result is not None
        else None
    )
    pipeline_result = {
        "schema_version": "asdi.main-verification-pipeline/v1",
        "action": action,
        "commit": landed_commit,
        "post_merge": result,
        "deployment": deployment,
        "deployed": False,
        "merge_executed": False,
        "appended_event_ids": [event["event_id"] for event in appended_events],
        "catch_up": catch_up,
        "verification_result_path": str(execution_result_path),
    }
    atomic_json(root_path / "latest-main-verification-pipeline.json", pipeline_result)
    return pipeline_result
