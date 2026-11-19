#!/usr/bin/env python3
"""Connect the PR policy gate to REV K's fail-closed merge dry run."""

from __future__ import annotations

from typing import Any

from merge.dry_run import evaluate


def evaluate_merge_packet(
    packet: dict[str, Any],
    *,
    actor: str,
    trm_level: str = "T0",
) -> dict[str, Any]:
    """Dry-run merge authority for one green, immutable PR packet."""

    if packet.get("schema_version") != "asdi.pr-packet/v1":
        raise ValueError("unsupported PR packet schema")
    policy_decision = packet.get("policy_decision")
    head_sha = packet.get("head_sha")
    if policy_decision != "eligible":
        return {
            "schema_version": "asdi.merge-dry-run/v1",
            "head_sha": head_sha,
            "actor": actor,
            "gate_decision": policy_decision,
            "merge_dry_run": None,
            "decision": "blocked",
            "human_required": False,
            "merge_executed": False,
            "reason": f"PR gate is {policy_decision}, not eligible",
        }
    classification = packet.get("classification", {})
    change_class = classification.get("change_class")
    if change_class not in {"agent_mergeable", "judgment"}:
        raise ValueError(f"unsupported packet change class: {change_class}")
    statuses = set(packet.get("statuses", {}))
    dry_run = evaluate(
        actor=actor,
        statuses=statuses,
        up_to_date=True,
        classification=change_class,
        trm_level=trm_level,
    )
    human_required = dry_run["decision"] in {"human_required", "refused"}
    return {
        "schema_version": "asdi.merge-dry-run/v1",
        "head_sha": head_sha,
        "actor": actor,
        "gate_decision": policy_decision,
        "merge_dry_run": dry_run,
        "decision": dry_run["decision"],
        "human_required": human_required and dry_run["decision"] != "refused",
        "merge_executed": False,
        "reason": dry_run["reason"],
    }
