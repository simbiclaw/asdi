from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from launcher.owner_decisions import OwnerDecisionLog


class OwnerDecisionStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.pilot_path = self.root / "existing-pilot"
        self.pilot_path.mkdir()
        self.log = OwnerDecisionLog(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def record(self, decision_type: str, choice: str, **kwargs) -> None:
        self.log.record(
            decision_type=decision_type,
            choice=choice,
            decided_by="repository_owner",
            decision_reference=f"{decision_type}-decision",
            direction="Direction supplied by the owner.",
            **kwargs,
        )

    def test_reports_both_decisions_pending(self) -> None:
        self.log.path.write_text("")
        status = self.log.status()
        self.assertFalse(status["ready_for_next_phase"])
        self.assertEqual(
            sorted(status["pending"]),
            ["independent_verifier", "phase3_pilot"],
        )
        self.assertFalse(
            status["decisions"]["phase3_pilot"]["phase3_can_start"]
        )

    def test_defer_is_recorded_but_does_not_start_phase3(self) -> None:
        self.record("independent_verifier", "owner_invoked_audit")
        self.record("phase3_pilot", "defer_phase3")
        status = self.log.status()
        self.assertFalse(status["ready_for_next_phase"])
        self.assertEqual(status["blocking"], ["phase3_pilot"])
        self.assertFalse(
            status["decisions"]["phase3_pilot"]["phase3_can_start"]
        )

    def test_synthetic_approval_enables_phase3(self) -> None:
        self.record(
            "independent_verifier",
            "readonly_audit_wrapper",
            runtime_command=["/usr/bin/true", "--audit"],
        )
        self.record("phase3_pilot", "approve_synthetic_toy_notes")
        status = self.log.status()
        self.assertTrue(status["ready_for_next_phase"])
        self.assertEqual(status["blocking"], [])
        self.assertTrue(
            status["decisions"]["phase3_pilot"]["phase3_can_start"]
        )

    def test_wrapper_choice_without_runtime_command_blocks(self) -> None:
        self.record("independent_verifier", "readonly_audit_wrapper")
        self.record("phase3_pilot", "approve_synthetic_toy_notes")
        status = self.log.status()
        self.assertFalse(status["ready_for_next_phase"])
        self.assertEqual(status["blocking"], ["independent_verifier"])

    def test_existing_pilot_requires_existing_absolute_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "existing absolute directory"):
            self.record(
                "phase3_pilot",
                "select_existing_pilot",
                selected_path="relative-pilot",
            )
        self.record(
            "phase3_pilot",
            "select_existing_pilot",
            selected_path=str(self.pilot_path),
        )
        self.assertEqual(
            self.log.status()["decisions"]["phase3_pilot"]["selected_path"],
            str(self.pilot_path),
        )

    def test_malformed_jsonl_fails_status_closed(self) -> None:
        path = self.log.path
        path.write_text("{broken}\n")
        with self.assertRaises(json.JSONDecodeError):
            self.log.status()
