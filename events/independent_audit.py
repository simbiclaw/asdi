#!/usr/bin/env python3
"""Durable ingestion for the owner-invoked cloud Claude PR audit."""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from launcher.owner_decisions import OwnerDecisionLog

from .journal import atomic_json


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
AUDIT_ID = re.compile(r"^ia-[A-Za-z0-9_-]{4,}$")
ISO_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
)
AUDIT_STATUSES = {"pass", "fail", "blocked"}
FINDING_BUCKETS = {"act", "consider", "noted", "dismissed"}


def active_owner_invoked_record(
    decision_log: OwnerDecisionLog,
) -> dict[str, Any]:
    """Return the latest verifier decision only after ledger-chain validation."""

    verification = decision_log.verify()
    if not verification.get("valid"):
        raise ValueError(
            "owner decision ledger is invalid: "
            + "; ".join(verification.get("failures", []))
        )
    record = decision_log.latest("independent_verifier")
    if record is None or record.get("choice") != "owner_invoked_audit":
        raise ValueError("no active owner_invoked_audit decision")
    return record


def validate_independent_audit(
    report: Any,
    *,
    decision_record: dict[str, Any],
) -> list[str]:
    """Validate one owner-provided cloud Claude audit without executing it."""

    failures: list[str] = []
    if not isinstance(report, dict):
        return ["independent audit is not an object"]
    required = {
        "schema_version",
        "audit_id",
        "source",
        "pr_number",
        "head_sha",
        "owner_decision_id",
        "operator",
        "completed_at",
        "gate_status",
        "verifier",
        "review",
        "findings",
    }
    missing = sorted(required - set(report))
    if missing:
        failures.append(f"missing fields: {', '.join(missing)}")
    if report.get("schema_version") != "asdi.independent-pr-audit/v1":
        failures.append("unsupported independent audit schema")
    audit_id = report.get("audit_id")
    if not isinstance(audit_id, str) or not AUDIT_ID.fullmatch(audit_id):
        failures.append("audit_id is invalid")
    if report.get("source") != "cloud_claude":
        failures.append("independent audit source must be cloud_claude")
    pr_number = report.get("pr_number")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        failures.append("pr_number must be a positive integer")
    head_sha = report.get("head_sha")
    if not isinstance(head_sha, str) or not FULL_SHA.fullmatch(head_sha):
        failures.append("head_sha must be a 40-character lowercase SHA")
    if report.get("owner_decision_id") != decision_record.get("decision_id"):
        failures.append("independent audit is not bound to the active owner decision")
    if report.get("operator") != decision_record.get("decided_by"):
        failures.append("independent audit operator does not match owner decision")
    completed_at = report.get("completed_at")
    if not isinstance(completed_at, str) or not ISO_TIMESTAMP.fullmatch(completed_at):
        failures.append("completed_at must be an ISO-8601 UTC timestamp")

    gate_status = report.get("gate_status")
    if gate_status not in AUDIT_STATUSES:
        failures.append("gate_status must be pass, fail or blocked")

    verifier = report.get("verifier")
    if not isinstance(verifier, dict):
        failures.append("verifier audit is not an object")
    else:
        if verifier.get("status") not in AUDIT_STATUSES:
            failures.append("verifier audit status is invalid")
        evidence = verifier.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            failures.append("verifier audit evidence must be a non-empty array")
        elif any(not isinstance(item, str) or not item for item in evidence):
            failures.append("verifier audit evidence entries must be non-empty strings")

    review = report.get("review")
    if not isinstance(review, dict):
        failures.append("review audit is not an object")
    else:
        if review.get("status") not in AUDIT_STATUSES:
            failures.append("review audit status is invalid")
        if not isinstance(review.get("model"), str) or not review.get("model"):
            failures.append("review audit model is required")
        if review.get("independent_context") is not True:
            failures.append("review audit must use an independent context")

    findings = report.get("findings")
    if not isinstance(findings, list):
        failures.append("findings must be an array")
    else:
        for index, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                failures.append(f"finding {index} is not an object")
                continue
            if finding.get("bucket") not in FINDING_BUCKETS:
                failures.append(f"finding {index} has an invalid bucket")
            if not isinstance(finding.get("claim"), str) or not finding.get("claim"):
                failures.append(f"finding {index} claim is required")
            if finding.get("bucket") == "act" and not finding.get("evidence"):
                failures.append(f"act finding {index} has no evidence")

    if gate_status == "pass":
        if isinstance(verifier, dict) and verifier.get("status") != "pass":
            failures.append("gate_status pass is inconsistent with verifier audit")
        if not isinstance(review, dict) or review.get("status") != "pass":
            failures.append("gate_status pass is inconsistent with review audit")
        if any(
            isinstance(finding, dict) and finding.get("bucket") == "act"
            for finding in findings or []
        ):
            failures.append("gate_status pass is inconsistent with act findings")
    return failures


class IndependentAuditStore:
    """Store one immutable audit per PR number and exact head."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, *, pr_number: int, head_sha: str) -> Path:
        return self.root / "independent-audits" / f"pr-{pr_number}" / f"{head_sha}.json"

    def ingest(
        self,
        report: dict[str, Any],
        *,
        decision_log: OwnerDecisionLog,
    ) -> dict[str, Any]:
        record = active_owner_invoked_record(decision_log)
        failures = validate_independent_audit(report, decision_record=record)
        if failures:
            raise ValueError("invalid independent audit: " + "; ".join(failures))
        destination = self.path(
            pr_number=report["pr_number"], head_sha=report["head_sha"]
        )
        atomic_json(destination, report)
        return {
            "schema_version": "asdi.independent-audit-ingestion/v1",
            "stored": True,
            "path": str(destination),
            "audit_id": report["audit_id"],
            "gate_status": report["gate_status"],
        }

    def load(
        self,
        *,
        pr_number: int,
        head_sha: str,
        decision_log: OwnerDecisionLog,
    ) -> dict[str, Any]:
        record = active_owner_invoked_record(decision_log)
        path = self.path(pr_number=pr_number, head_sha=head_sha)
        if not path.is_file():
            raise FileNotFoundError(f"independent audit is pending: {path}")
        report = json.loads(path.read_text())
        failures = validate_independent_audit(report, decision_record=record)
        if failures:
            raise ValueError("invalid independent audit: " + "; ".join(failures))
        return report


def apply_independent_audit(
    packet: dict[str, Any],
    *,
    audit: dict[str, Any] | None,
    failures: list[str] | None = None,
) -> dict[str, Any]:
    """Attach the independent audit and downgrade the packet when not green."""

    normalized = {
        "required": True,
        "source": "cloud_claude",
        "status": "missing" if audit is None else audit.get("gate_status"),
        "audit_id": audit.get("audit_id") if audit else None,
        "failures": failures or [],
    }
    packet["independent_audit"] = normalized
    base_policy = packet.setdefault(
        "base_policy_decision",
        packet.get("policy_decision"),
    )
    if audit is not None:
        packet["failures"] = [
            *packet.get("failures", []),
            *normalized["failures"],
        ]
    if normalized["status"] != "pass" or normalized["failures"]:
        packet["policy_decision"] = "blocked"
        packet["statuses"]["asdi/policy"] = "fail"
    else:
        packet["policy_decision"] = base_policy
        packet["statuses"]["asdi/policy"] = (
            "pass"
            if base_policy in {"eligible", "human_required"}
            else "fail"
        )
    return packet


def audit_for_packet(
    *,
    store: IndependentAuditStore,
    decision_log: OwnerDecisionLog,
    pr_number: int,
    head_sha: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        return store.load(
            pr_number=pr_number,
            head_sha=head_sha,
            decision_log=decision_log,
        ), []
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        return None, [str(error)]


def audit_template(
    *,
    decision_log: OwnerDecisionLog,
    pr_number: int,
    head_sha: str,
) -> dict[str, Any]:
    """Create a prefilled owner template for the selected exact PR head."""

    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise ValueError("pr_number must be a positive integer")
    if not isinstance(head_sha, str) or not FULL_SHA.fullmatch(head_sha):
        raise ValueError("head_sha must be a 40-character lowercase SHA")
    decision_record = active_owner_invoked_record(decision_log)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    audit_id = f"ia-cloud-claude-{uuid.uuid4().hex[:12]}"
    return {
        "schema_version": "asdi.independent-pr-audit/v1",
        "audit_id": audit_id,
        "source": "cloud_claude",
        "pr_number": pr_number,
        "head_sha": head_sha,
        "owner_decision_id": decision_record.get("decision_id"),
        "operator": decision_record.get("decided_by"),
        "completed_at": timestamp,
        "gate_status": "blocked",
        "verifier": {
            "status": "blocked",
            "evidence": ["<replace with exact-head verification evidence>"],
        },
        "review": {
            "status": "blocked",
            "model": "cloud-claude",
            "independent_context": True,
        },
        "findings": [],
    }


