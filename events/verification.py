#!/usr/bin/env python3
"""Map verified launcher evidence into a durable PR-gate event."""

from __future__ import annotations

from typing import Any


CI_STATUSES = {"pass", "fail", "blocked", "error"}


def verification_event_payload(
    *,
    packet: dict[str, Any],
    evidence: dict[str, Any],
    ci_status: str,
) -> dict[str, Any]:
    """Return only the gate-contract subset of a verified evidence manifest."""

    pr_number = packet.get("pr_number")
    head_sha = packet.get("head_sha")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise ValueError("packet has no valid pr_number")
    if not isinstance(head_sha, str) or not head_sha:
        raise ValueError("packet has no valid head_sha")
    if ci_status not in CI_STATUSES:
        raise ValueError("ci_status must be pass, fail, blocked or error")
    if not isinstance(evidence, dict) or evidence.get("valid") is not True:
        raise ValueError("evidence is not verified")
    if not isinstance(evidence.get("manifest_id"), str) or not evidence["manifest_id"]:
        raise ValueError("evidence has no manifest_id")
    statement = evidence.get("statement")
    result = evidence.get("result")
    if not isinstance(statement, dict) or not isinstance(result, dict):
        raise ValueError("verified evidence is missing statement or result")

    subject = statement.get("subject")
    if (
        not isinstance(subject, list)
        or len(subject) != 1
        or not isinstance(subject[0], dict)
        or subject[0].get("digest", {}).get("gitCommit") != head_sha
    ):
        raise ValueError("evidence subject is not bound to packet head")
    if result.get("commit") != head_sha:
        raise ValueError("evidence result is not bound to packet head")
    run_id = result.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("evidence result has no run_id")
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict) or predicate.get("source") != "pr-head":
        raise ValueError("PR gate requires evidence source pr-head")

    features = result.get("features")
    failures: list[str] = []
    if not isinstance(features, list) or not features:
        failures.append("evidence result has no features")
    else:
        for index, feature in enumerate(features, start=1):
            if not isinstance(feature, dict):
                failures.append(f"feature {index} is not an object")
                continue
            if feature.get("status") != "pass":
                failures.append(f"feature {feature.get('id', index)} is not pass")
            if feature.get("control") != "caught":
                failures.append(f"feature {feature.get('id', index)} control was not caught")
            if not isinstance(feature.get("limits"), list):
                failures.append(f"feature {feature.get('id', index)} has no limits list")

    verifier = {
        "candidate_commit": head_sha,
        "status": "fail" if failures else "pass",
        "manifest_id": evidence["manifest_id"],
        "run_id": run_id,
    }
    if failures:
        verifier["failures"] = failures
    return {
        "pr_number": pr_number,
        "head_sha": head_sha,
        "statuses": {"ci": ci_status},
        "verifier": verifier,
    }
