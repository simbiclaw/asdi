#!/usr/bin/env python3
"""Connect the PR policy gate to REV K's fail-closed merge dry run."""

from __future__ import annotations

import re
from typing import Any

from merge.dry_run import evaluate


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
UP_TO_DATE_KEYS = ("up_to_date", "branch_up_to_date", "branch_fresh")
BASE_SHA_KEYS = ("base_sha", "base_commit")
MAIN_SHA_KEYS = ("main_sha", "current_main_sha", "main_commit", "current_main_commit")
NESTED_FRESHNESS_KEYS = (
    "branch_freshness",
    "freshness",
    "branch",
    "base",
    "main",
    "current_main",
)


def _full_sha(value: Any) -> str | None:
    if isinstance(value, str) and FULL_SHA.fullmatch(value):
        return value
    return None


def _freshness_sources(packet: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sources: list[tuple[str, dict[str, Any]]] = [("packet", packet)]
    for key in NESTED_FRESHNESS_KEYS:
        value = packet.get(key)
        if isinstance(value, dict):
            sources.append((key, value))
    return sources


def _evaluate_freshness(packet: dict[str, Any]) -> tuple[bool | None, dict[str, Any]]:
    up_to_date: bool | None = None
    up_to_date_source: str | None = None
    base_sha: str | None = None
    main_sha: str | None = None

    for source_name, source in _freshness_sources(packet):
        if up_to_date is None:
            for key in UP_TO_DATE_KEYS:
                value = source.get(key)
                if isinstance(value, bool):
                    up_to_date = value
                    up_to_date_source = f"{source_name}.{key}"
                    break
        if base_sha is None:
            keys = BASE_SHA_KEYS + (("sha",) if source_name in {"base", "branch"} else ())
            for key in keys:
                base_sha = _full_sha(source.get(key))
                if base_sha is not None:
                    break
        if main_sha is None:
            keys = MAIN_SHA_KEYS + (("sha",) if source_name in {"main", "current_main"} else ())
            for key in keys:
                main_sha = _full_sha(source.get(key))
                if main_sha is not None:
                    break

    if base_sha is not None and main_sha is not None:
        derived = base_sha == main_sha
        evidence: dict[str, Any] = {
            "evaluated": True,
            "up_to_date": derived,
            "basis": "base_sha compared with current main sha",
            "base_sha": base_sha,
            "main_sha": main_sha,
        }
        if up_to_date is not None and up_to_date != derived:
            evidence["conflict"] = "explicit freshness flag disagrees with sha comparison"
            return False, evidence
        return derived, evidence

    if up_to_date is not None:
        return up_to_date, {
            "evaluated": True,
            "up_to_date": up_to_date,
            "basis": up_to_date_source,
        }
    return None, {
        "evaluated": False,
        "up_to_date": None,
        "basis": None,
        "reason": "PR packet has no branch freshness evidence",
    }


def _passing_statuses(packet: dict[str, Any]) -> set[str]:
    statuses = packet.get("statuses")
    if not isinstance(statuses, dict):
        return set()
    return {name for name, value in statuses.items() if value == "pass"}


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
    statuses = _passing_statuses(packet)
    up_to_date, freshness = _evaluate_freshness(packet)
    dry_run = evaluate(
        actor=actor,
        statuses=statuses,
        up_to_date=True if up_to_date is None else up_to_date,
        classification=change_class,
        trm_level=trm_level,
    )
    if up_to_date is None:
        dry_run["up_to_date"] = None
        dry_run["freshness_evaluated"] = False
        dry_run.setdefault("rules_fired", []).append("R9-branch-freshness-not-evaluated")
        dry_run["reason"] = f"{dry_run['reason']}; branch freshness not evaluated"
    else:
        dry_run["freshness_evaluated"] = True
    human_required = dry_run["decision"] in {"human_required", "refused"}
    return {
        "schema_version": "asdi.merge-dry-run/v1",
        "head_sha": head_sha,
        "actor": actor,
        "gate_decision": policy_decision,
        "merge_dry_run": dry_run,
        "decision": dry_run["decision"],
        "branch_freshness": freshness,
        "human_required": human_required and dry_run["decision"] != "refused",
        "merge_executed": False,
        "reason": dry_run["reason"],
    }
