#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from events.independent_audit import (
    IndependentAuditStore,
    apply_independent_audit,
    validate_independent_audit,
)
from launcher.owner_decisions import OwnerDecisionLog


HEAD = "a" * 40


def report() -> dict:
    return {
        "schema_version": "asdi.independent-pr-audit/v1",
        "audit_id": "ia-cloud-claude-001",
        "source": "cloud_claude",
        "pr_number": 7,
        "head_sha": HEAD,
        "owner_decision_id": "decision-id",
        "operator": "repository_owner",
        "completed_at": "2026-11-20T00:00:00Z",
        "gate_status": "pass",
        "verifier": {
            "status": "pass",
            "evidence": ["manifest m-test; all features caught"],
        },
        "review": {
            "status": "pass",
            "model": "cloud-claude",
            "independent_context": True,
        },
        "findings": [],
    }


class IndependentAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.log = OwnerDecisionLog(self.root)
        self.record = self.log.record(
            decision_type="independent_verifier",
            choice="owner_invoked_audit",
            decided_by="repository_owner",
            decision_reference="owner direction 2026-11-20",
            direction="Use the cloud Claude verify-then-review gate.",
        )
        self.store = IndependentAuditStore(self.root)
        self.value = report()
        self.value["owner_decision_id"] = self.record["decision_id"]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_audit_is_bound_and_durable(self) -> None:
        failures = validate_independent_audit(
            self.value,
            decision_record=self.record,
        )
        self.assertEqual(failures, [])
        result = self.store.ingest(self.value, decision_log=self.log)
        self.assertTrue(result["stored"])
        loaded = self.store.load(
            pr_number=7,
            head_sha=HEAD,
            decision_log=self.log,
        )
        self.assertEqual(loaded["audit_id"], "ia-cloud-claude-001")

    def test_mismatched_head_or_decision_is_rejected(self) -> None:
        self.value["head_sha"] = "stale-head"
        failures = validate_independent_audit(
            self.value,
            decision_record=self.record,
        )
        self.assertIn(
            "head_sha must be a 40-character lowercase SHA",
            failures,
        )
        self.value["head_sha"] = HEAD
        self.value["owner_decision_id"] = "other-decision"
        with self.assertRaises(ValueError):
            self.store.ingest(self.value, decision_log=self.log)

    def test_missing_or_failed_audit_downgrades_packet(self) -> None:
        packet = {
            "policy_decision": "eligible",
            "statuses": {"ci": "pass", "asdi/policy": "pass"},
            "failures": [],
        }
        blocked = apply_independent_audit(packet, audit=None, failures=["audit pending"])
        self.assertEqual(blocked["policy_decision"], "blocked")
        self.assertEqual(blocked["statuses"]["asdi/policy"], "fail")
        self.assertEqual(blocked["independent_audit"]["status"], "missing")

        packet = {
            "policy_decision": "eligible",
            "statuses": {"ci": "pass", "asdi/policy": "pass"},
            "failures": [],
        }
        self.value["gate_status"] = "blocked"
        failed = apply_independent_audit(packet, audit=self.value, failures=[])
        self.assertEqual(failed["policy_decision"], "blocked")
        self.assertEqual(failed["independent_audit"]["status"], "blocked")

    def test_green_audit_keeps_policy_packet_eligible(self) -> None:
        packet = {
            "policy_decision": "eligible",
            "statuses": {"ci": "pass", "asdi/policy": "pass"},
            "failures": [],
        }
        enriched = apply_independent_audit(packet, audit=self.value, failures=[])
        self.assertEqual(enriched["policy_decision"], "eligible")
        self.assertEqual(enriched["independent_audit"]["status"], "pass")
        self.assertTrue(enriched["independent_audit"]["required"])
