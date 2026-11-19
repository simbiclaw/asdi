#!/usr/bin/env python3
"""Fail-closed REV K Pass 1 PR-gate core and post-merge policy."""

from __future__ import annotations

from typing import Any

from .classifier import classify_changed_paths, load_mapping


REQUIRED_STATUSES = {"ci", "asdi/policy"}


def _required(value: dict[str, Any], key: str) -> Any:
    if key not in value:
        raise ValueError(f"missing {key}")
    return value[key]


class PRGate:
    """Evaluate a single immutable PR head using locally gathered evidence."""

    def __init__(
        self,
        *,
        class_config: dict[str, Any],
        feature_map: dict[str, list[str]],
        base_ref: str = "main",
    ) -> None:
        self.class_config = class_config
        self.feature_map = load_mapping(feature_map)
        self.base_ref = base_ref

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        pr_number = int(_required(payload, "pr_number"))
        head_sha = str(_required(payload, "head_sha"))
        base_ref = str(payload.get("base_ref", self.base_ref))
        paths = list(_required(payload, "changed_paths"))
        statuses = dict(payload.get("statuses", {}))
        review = dict(payload.get("review", {}))
        verifier = dict(payload.get("verifier", {}))

        classification = classify_changed_paths(
            paths=paths,
            feature_map=self.feature_map,
            class_config=self.class_config,
        )
        failures: list[str] = []
        if base_ref != self.base_ref:
            failures.append(f"unexpected base ref {base_ref}")
        missing_statuses = sorted(REQUIRED_STATUSES - set(statuses))
        if missing_statuses:
            failures.append(f"missing statuses: {', '.join(missing_statuses)}")
        if statuses.get("ci") != "pass":
            failures.append("ci is not pass")
        if verifier.get("candidate_commit") != head_sha:
            failures.append("verifier is not bound to PR head")
        if verifier.get("status") != "pass":
            failures.append("verifier is not pass")
        if review.get("reviewed_commit") != head_sha:
            failures.append("review is not bound to PR head")
        if review.get("passed") is not True:
            failures.append("review is not pass")

        decision = "eligible"
        if classification["split_required"]:
            decision = "split_required"
        elif failures:
            decision = "blocked"
        elif classification["human_required"]:
            decision = "human_required"

        packet = {
            "schema_version": "asdi.pr-packet/v1",
            "pr_number": pr_number,
            "head_sha": head_sha,
            "base_ref": base_ref,
            "changed_paths": sorted(paths),
            "statuses": statuses,
            "verifier": verifier,
            "review": review,
            "classification": classification,
            "failures": failures,
            "policy_decision": decision,
        }
        return {
            "pr_number": pr_number,
            "head_sha": head_sha,
            "decision": decision,
            "human_required": decision == "human_required",
            "split_required": decision == "split_required",
            "failures": failures,
            "packet": packet,
        }


def post_merge_check(payload: dict[str, Any]) -> dict[str, Any]:
    commit = str(_required(payload, "commit"))
    statuses = dict(payload.get("statuses", {}))
    verifier = dict(payload.get("verifier", {}))
    failures: list[str] = []
    if statuses.get("ci") != "pass":
        failures.append("main ci is not pass")
    if verifier.get("candidate_commit") != commit:
        failures.append("main verifier is not bound to commit")
    if verifier.get("status") != "pass":
        failures.append("main verifier is not pass")
    result = {
        "commit": commit,
        "passed": not failures,
        "failures": failures,
        "deployment_eligible": not failures,
    }
    if failures:
        result["auto_revert"] = {
            "required": True,
            "reverted_commit": commit,
            "branch": f"auto-revert/{commit[:12]}",
            "reason": "; ".join(failures),
        }
    return result


def deployment_decision(
    *,
    commit: str,
    main_results: list[dict[str, Any]],
) -> dict[str, Any]:
    matching = [
        result
        for result in main_results
        if result.get("commit") == commit and result.get("passed") is True
    ]
    if not matching:
        return {
            "commit": commit,
            "eligible": False,
            "reason": "no passing post-merge result for exact commit",
        }
    return {
        "commit": commit,
        "eligible": True,
        "post_merge": matching[-1],
    }
