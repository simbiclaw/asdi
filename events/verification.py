#!/usr/bin/env python3
"""Map verified launcher evidence into a durable PR-gate event."""

from __future__ import annotations

from typing import Any


CI_STATUSES = {"pass", "fail", "blocked", "error"}
EVIDENCE_SOURCES = {"pr-head", "main"}


def verification_event_payload(
    *,
    packet: dict[str, Any],
    evidence: dict[str, Any],
    ci_status: str,
) -> dict[str, Any]:
    """Return the gate-contract subset of verified PR-head evidence."""

    pr_number = packet.get("pr_number")
    head_sha = packet.get("head_sha")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise ValueError("packet has no valid pr_number")
    if not isinstance(head_sha, str) or not head_sha:
        raise ValueError("packet has no valid head_sha")
    if ci_status not in CI_STATUSES:
        raise ValueError("ci_status must be pass, fail, blocked or error")
    verifier = verified_evidence_contract(
        evidence=evidence,
        commit=head_sha,
        source="pr-head",
    )
    return {
        "pr_number": pr_number,
        "head_sha": head_sha,
        "statuses": {"ci": ci_status},
        "verifier": verifier,
    }


def main_verification_event_payload(
    *,
    commit: str,
    evidence: dict[str, Any],
    ci_status: str,
) -> dict[str, Any]:
    """Return the gate-contract subset of verified exact-``main`` evidence."""

    if ci_status not in CI_STATUSES:
        raise ValueError("ci_status must be pass, fail, blocked or error")
    verifier = verified_evidence_contract(
        evidence=evidence,
        commit=commit,
        source="main",
    )
    return {
        "commit": commit,
        "statuses": {"ci": ci_status},
        "verifier": verifier,
    }


def verified_evidence_contract(
    *,
    evidence: dict[str, Any],
    commit: str,
    source: str,
) -> dict[str, Any]:
    """Validate one verified manifest and return its normalized verifier."""

    if source not in EVIDENCE_SOURCES:
        raise ValueError("evidence source must be pr-head or main")
    if not isinstance(commit, str) or not commit:
        raise ValueError("evidence commit is required")
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
        or subject[0].get("digest", {}).get("gitCommit") != commit
    ):
        raise ValueError("evidence subject is not bound to target commit")
    if result.get("commit") != commit:
        raise ValueError("evidence result is not bound to target commit")
    run_id = result.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("evidence result has no run_id")
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict) or predicate.get("source") != source:
        raise ValueError(f"{source} gate requires evidence source {source}")
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
        "candidate_commit": commit,
        "status": "fail" if failures else "pass",
        "manifest_id": evidence["manifest_id"],
        "run_id": run_id,
    }
    if failures:
        verifier["failures"] = failures
    return verifier
