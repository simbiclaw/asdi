#!/usr/bin/env python3
"""Map verified launcher evidence into a durable PR-gate event."""

from __future__ import annotations

from typing import Any


EVIDENCE_SOURCES = {"pr-head", "main"}


def ci_status_from_checks(value: Any) -> str:
    """Derive CI from the named static gates, ignoring other verifier checks."""

    if not isinstance(value, list):
        return "error"
    checks = [
        check
        for check in value
        if isinstance(check, dict)
        and str(check.get("id", "")).startswith("static:")
    ]
    if not checks:
        return "error"
    if any(check.get("status") in {"error", "blocked"} for check in checks):
        return "error"
    if any(
        check.get("blocking", True) is True and check.get("status") != "pass"
        for check in checks
    ):
        return "fail"
    if any(
        check.get("blocking", True) is False and check.get("status") == "fail"
        for check in checks
    ):
        return "pass"
    if all(check.get("status") == "pass" for check in checks):
        return "pass"
    return "error"


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
    verifier = verified_evidence_contract(
        evidence=evidence,
        commit=head_sha,
        source="pr-head",
        ci_status=ci_status,
    )
    return {
        "pr_number": pr_number,
        "head_sha": head_sha,
        "statuses": {"ci": verifier["ci_status"]},
        "verifier": verifier,
    }


def main_verification_event_payload(
    *,
    commit: str,
    evidence: dict[str, Any],
    ci_status: str,
) -> dict[str, Any]:
    """Return the gate-contract subset of verified exact-``main`` evidence."""

    verifier = verified_evidence_contract(
        evidence=evidence,
        commit=commit,
        source="main",
        ci_status=ci_status,
    )
    return {
        "commit": commit,
        "statuses": {"ci": verifier["ci_status"]},
        "verifier": verifier,
    }


def verified_evidence_contract(
    *,
    evidence: dict[str, Any],
    commit: str,
    source: str,
    ci_status: str | None = None,
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
    static_checks = predicate.get("static_checks")
    if not isinstance(static_checks, dict):
        static_checks = []
    derived_ci = ci_status_from_checks(
        static_checks.get("checks") if isinstance(static_checks, dict) else static_checks
    )
    features = result.get("features")
    failures: list[str] = []
    if not isinstance(predicate.get("static_checks"), dict):
        failures.append("evidence statement has no static_checks")
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
        "ci_status": derived_ci,
    }
    if failures:
        verifier["failures"] = failures
    if ci_status is not None and ci_status != derived_ci:
        verifier["status"] = "fail"
        failures = verifier.setdefault("failures", [])
        failures.append(
            f"declared ci status {ci_status!r} does not match derived status {derived_ci!r}"
        )
    return verifier
