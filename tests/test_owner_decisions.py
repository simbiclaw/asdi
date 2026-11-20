from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from launcher.owner_decisions import OwnerDecisionLog, record_digest


class OwnerDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.log = OwnerDecisionLog(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def record_verifier(self) -> dict:
        return self.log.record(
            decision_type="independent_verifier",
            choice="readonly_audit_wrapper",
            decided_by="repository_owner",
            decision_reference="decision-2026-11-18-verifier",
            direction="Use the capability-restricted wrapper.",
            runtime_command=["/usr/bin/python3", "/opt/asdi/audit.py"],
        )

    def test_hash_chained_owner_decisions_are_durable(self) -> None:
        first = self.record_verifier()
        second = self.log.record(
            decision_type="phase3_pilot",
            choice="approve_synthetic_toy_notes",
            decided_by="repository_owner",
            decision_reference="decision-2026-11-18-pilot",
            direction="Build the smallest synthetic pilot only.",
        )
        records = self.log.records()
        self.assertEqual(len(records), 2)
        self.assertEqual(first["record_sha256"], record_digest(first))
        self.assertEqual(
            second["previous_record_sha256"],
            first["record_sha256"],
        )
        self.assertEqual(second["runtime_command"], [])
        self.assertIsNone(second["selected_path"])

    def test_rejects_unknown_choice_and_secret_like_runtime(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown decision type"):
            self.log.record(
                decision_type="unknown",
                choice="anything",
                decided_by="owner",
                decision_reference="ref",
                direction="direction",
            )
        with self.assertRaisesRegex(ValueError, "choice must be one of"):
            self.log.record(
                decision_type="independent_verifier",
                choice="trust_the_agent",
                decided_by="owner",
                decision_reference="ref",
                direction="direction",
            )
        with self.assertRaisesRegex(ValueError, "credential-like"):
            self.log.record(
                decision_type="independent_verifier",
                choice="other_enforced_runtime",
                decided_by="owner",
                decision_reference="ref",
                direction="direction",
                runtime_command=["/usr/bin/env", "GITHUB_TOKEN=secret"],
            )

    def test_existing_pilot_requires_path_and_verification_detects_tamper(self) -> None:
        with self.assertRaisesRegex(ValueError, "existing pilot requires"):
            self.log.record(
                decision_type="phase3_pilot",
                choice="select_existing_pilot",
                decided_by="owner",
                decision_reference="ref",
                direction="direction",
            )
        record = self.record_verifier()
        path = self.log.path
        stored = [json.loads(line) for line in path.read_text().splitlines() if line]
        stored[0]["choice"] = "owner_invoked_audit"
        path.write_text("\n".join(json.dumps(item) for item in stored) + "\n")
        result = self.log.verify()
        self.assertFalse(result["valid"])
        self.assertTrue(result["failures"])
        self.assertEqual(record["decision_type"], "independent_verifier")
