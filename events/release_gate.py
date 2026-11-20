#!/usr/bin/env python3
"""Fail-closed release readiness for an exact passing ``main`` commit."""

from __future__ import annotations

import re
from typing import Any

from .pr_gate import deployment_decision


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
ARTIFACT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def release_readiness(
    *,
    commit: str,
    artifact_digest: str,
    main_state: dict[str, Any] | None,
    current_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a human-gated release request; never authorize execution."""

    failures: list[str] = []
    if not isinstance(commit, str) or not FULL_SHA.fullmatch(commit):
        failures.append("release commit must be a 40-character lowercase SHA")
    if not isinstance(artifact_digest, str) or not ARTIFACT_DIGEST.fullmatch(artifact_digest):
        failures.append("release artifact must be bound to a sha256 digest")
    if not isinstance(main_state, dict) or main_state.get("schema_version") != "asdi.main-state/v1":
        failures.append("no durable main state for release commit")
    else:
        if main_state.get("commit") != commit:
            failures.append("main state is not bound to release commit")
        if main_state.get("branch") != "main":
            failures.append("release requires a main state")
        result = main_state.get("result")
        if not isinstance(result, dict):
            failures.append("release commit has no post-merge result")
        else:
            deployment = deployment_decision(commit=commit, main_results=[result])
            if not deployment.get("eligible"):
                failures.append(deployment.get("reason", "release commit is not deployment eligible"))
    if current_state is not None and current_state.get("commit") != commit:
        failures.append("release commit is no longer current main")

    return {
        "schema_version": "asdi.release-readiness/v1",
        "commit": commit,
        "artifact_digest": artifact_digest,
        "decision": "blocked" if failures else "ready",
        "deployment_eligible": not failures,
        "human_required": True,
        "release_executed": False,
        "failures": failures,
    }
