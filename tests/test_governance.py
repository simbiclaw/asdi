from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asdi.governance import TRMLedger


class TRMLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.ledger = TRMLedger(self.root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_three_first_passes_promote_t0_to_t1(self) -> None:
        for index in range(3):
            transition = self.ledger.record_first_pass(
                task_type="feature",
                mission_id=f"mission_{index}",
                evidence={"review": "pass"},
            )
        self.assertEqual(self.ledger.snapshot()["task_types"]["feature"]["maturity"], "T1")
        self.assertEqual(transition["reason"], "three first-pass approvals (3)")

    def test_t1_requires_five_approvals_and_thirty_day_stability(self) -> None:
        for index in range(3):
            self.ledger.record_first_pass(
                task_type="feature",
                mission_id=f"promotion-{index}",
                evidence={"review": "pass"},
            )
        for index in range(4):
            self.ledger.record_first_pass(
                task_type="feature",
                mission_id=f"stable-{index}",
                evidence={"review": "pass"},
                occurred_at="2027-01-01T00:00:00Z",
            )
        self.assertEqual(self.ledger.snapshot()["task_types"]["feature"]["maturity"], "T1")
        event = self.ledger.record_first_pass(
            task_type="feature",
            mission_id="stable-boundary",
            evidence={"review": "pass"},
                occurred_at="2027-01-02T00:00:00Z",
        )
        first_pass_event = self.ledger.events()[-2]
        self.assertIsNone(first_pass_event.get("promotion_blocked"))
        self.assertEqual(self.ledger.snapshot()["task_types"]["feature"]["maturity"], "T2")

    def test_t1_before_thirty_days_does_not_promote(self) -> None:
        for index in range(3):
            self.ledger.record_first_pass(
                task_type="feature",
                mission_id=f"promotion-{index}",
                evidence={"review": "pass"},
            )
        for index in range(5):
            self.ledger.record_first_pass(
                task_type="feature",
                mission_id=f"too-soon-{index}",
                evidence={"review": "pass"},
                occurred_at="2026-01-10T00:00:00Z",
            )
        self.assertEqual(self.ledger.snapshot()["task_types"]["feature"]["maturity"], "T1")

    def test_t1_revert_demotes_to_t0(self) -> None:
        for index in range(3):
            self.ledger.record_first_pass(
                task_type="feature",
                mission_id=f"promotion-{index}",
                evidence={"review": "pass"},
            )
        self.ledger.record_revert(
            task_type="feature",
            evidence={"commit": "bad"},
        )
        self.assertEqual(self.ledger.snapshot()["task_types"]["feature"]["maturity"], "T0")

    def test_t2_revert_and_escaped_defect_demote_to_t0(self) -> None:
        task = self.ledger._task("feature")
        task["maturity"] = "T2"
        self.ledger._save()
        self.ledger.record_revert(task_type="feature", evidence={"commit": "bad"})
        self.assertEqual(self.ledger.snapshot()["task_types"]["feature"]["maturity"], "T0")
        task = self.ledger._task("other")
        task["maturity"] = "T2"
        self.ledger._save()
        self.ledger.record_escaped_defect(
            task_type="other", evidence={"defect": "escaped"}
        )
        self.assertEqual(self.ledger.snapshot()["task_types"]["other"]["maturity"], "T0")

    def test_two_consecutive_t2_resets_demote_to_t1(self) -> None:
        task = self.ledger._task("feature")
        task["maturity"] = "T2"
        self.ledger._save()
        self.ledger.record_reset(task_type="feature", evidence={"reset": 1})
        self.ledger.record_reset(task_type="feature", evidence={"reset": 2})
        self.assertEqual(self.ledger.snapshot()["task_types"]["feature"]["maturity"], "T1")

    def test_model_release_demotes_and_evaluation_restores(self) -> None:
        task = self.ledger._task("feature")
        task["maturity"] = "T2"
        self.ledger._save()
        self.ledger.record_model_release(release_id="model-2")
        self.assertEqual(self.ledger.snapshot()["task_types"]["feature"]["maturity"], "T1")
        self.ledger.record_evaluation_passed(
            release_id="model-2", evidence={"suite": "pass"}
        )
        self.assertEqual(self.ledger.snapshot()["task_types"]["feature"]["maturity"], "T2")

    def test_judgment_path_caps_effective_supervision_at_t1(self) -> None:
        task = self.ledger._task("judgment")
        task["maturity"] = "T2"
        self.ledger._save()
        self.ledger.mark_judgment_path(task_type="judgment")
        self.assertEqual(
            self.ledger.snapshot()["task_types"]["judgment"]["effective_maturity"],
            "T1",
        )
