#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from events.main_workflow import MainWorkflowStore


COMMIT = "a" * 40


class MainWorkflowStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = MainWorkflowStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def push(self, event_id: int = 1) -> dict:
        return {
            "event_id": event_id,
            "event_type": "github.push",
            "payload": {"branch": "main", "commit": COMMIT},
        }

    def verification(self, event_id: int = 2, status: str = "pass") -> dict:
        return {
            "event_id": event_id,
            "event_type": "github.main_verification_completed",
            "payload": {
                "commit": COMMIT,
                "statuses": {"ci": status},
                "verifier": {
                    "candidate_commit": COMMIT,
                    "status": status,
                    "manifest_id": "m-main",
                    "run_id": "r-main",
                },
            },
        }

    def test_exact_passing_main_is_deployment_eligible(self) -> None:
        self.store.apply(self.push())
        result = self.store.apply(self.verification())

        self.assertEqual(result["action"], "verification_recorded")
        self.assertTrue(result["result"]["deployment_eligible"])
        self.assertTrue(result["deployment"]["eligible"])
        self.assertTrue(
            (self.root / "main-results" / f"{COMMIT}.json").is_file()
        )

    def test_failed_main_plans_auto_revert_and_blocks_deployment(self) -> None:
        self.store.apply(self.push())
        result = self.store.apply(self.verification(status="fail"))

        self.assertFalse(result["result"]["deployment_eligible"])
        self.assertFalse(result["deployment"]["eligible"])
        self.assertEqual(
            result["result"]["auto_revert"]["reverted_commit"],
            COMMIT,
        )

    def test_stale_result_cannot_authorize_new_commit(self) -> None:
        self.store.apply(self.push())
        self.store.apply(self.verification())
        new_commit = "b" * 40
        self.store.apply({
            "event_id": 3,
            "event_type": "github.push",
            "payload": {"branch": "main", "commit": new_commit},
        })
        result = self.store.apply({
            "event_id": 4,
            "event_type": "github.main_verification_completed",
            "payload": {
                "commit": new_commit,
                "statuses": {"ci": "pass"},
                "verifier": {
                    "candidate_commit": COMMIT,
                    "status": "pass",
                    "manifest_id": "m-main",
                    "run_id": "r-main",
                },
            },
        })

        self.assertEqual(result["action"], "invalid_verification_payload")
        self.assertIn(
            "verifier is not bound to main commit",
            result["failures"],
        )
        self.assertTrue((self.root / "main-state" / f"{COMMIT}.json").is_file())
        self.assertTrue((self.root / "main-state" / f"{new_commit}.json").is_file())
