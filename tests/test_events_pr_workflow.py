#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from events.pr_workflow import PRWorkflowStore


HEAD_A = "a" * 40
HEAD_B = "b" * 40
OLD_HEAD = "0" * 40


def pull_request_payload(head: str = HEAD_A, pr_number: int = 7) -> dict:
    return {
        "pr_number": pr_number,
        "head_sha": head,
        "base_ref": "main",
        "changed_paths": ["src/feature.py"],
        "statuses": {"ci": "pass", "asdi/policy": "pass"},
        "verifier": {"candidate_commit": head, "status": "pass"},
    }


def review_payload(head: str = HEAD_A, event_id: int = 2) -> dict:
    return {
        "event_id": event_id,
        "event_type": "github.review_completed",
        "payload": {
            "pr_number": 7,
            "head_sha": head,
            "review": {
                "reviewed_commit": head,
                "passed": True,
                "status": "pass",
            },
        },
    }


def verification_payload(head: str = HEAD_A, event_id: int = 2) -> dict:
    return {
        "event_id": event_id,
        "event_type": "github.verification_completed",
        "payload": {
            "pr_number": 7,
            "head_sha": head,
            "statuses": {"ci": "pass"},
            "verifier": {
                "candidate_commit": head,
                "status": "pass",
                "manifest_id": "m-test",
                "run_id": "r-test",
            },
        },
    }


class PRWorkflowStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = PRWorkflowStore(
            self.root,
            class_config={
                "judgment_paths": ["src/auth/**"],
                "agent_mergeable_paths": ["src/**"],
            },
            feature_map={"notes": ["src/**"]},
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def initial_event(self, head: str = HEAD_A, event_id: int = 1) -> dict:
        return {
            "event_id": event_id,
            "event_type": "github.pull_request",
            "payload": pull_request_payload(head),
        }

    def minimal_initial_event(self, head: str = HEAD_A, event_id: int = 1) -> dict:
        payload = pull_request_payload(head)
        payload.pop("statuses")
        payload.pop("verifier")
        return {
            "event_id": event_id,
            "event_type": "github.pull_request",
            "payload": payload,
        }

    def test_initial_pull_request_is_pending_without_review(self) -> None:
        result = self.store.apply(self.initial_event())

        self.assertEqual(result["action"], "pull_request_recorded")
        self.assertIsNone(result["gate"])
        self.assertIsNone(result["packet"])
        self.assertIsNone(result["state"]["review"])
        self.assertEqual(result["state"]["gate_decision"], "pending_review")
        state_path = self.root / "pr-state/pr-7" / f"{HEAD_A}.json"
        self.assertTrue(state_path.is_file())
        self.assertEqual(
            json.loads((self.root / "pr-state/pr-7/current.json").read_text())[
                "head_sha"
            ],
            HEAD_A,
        )

    def test_review_completion_evaluates_and_persists_separate_packet(self) -> None:
        self.store.apply(self.initial_event())
        result = self.store.apply(review_payload())

        self.assertEqual(result["action"], "review_recorded")
        self.assertEqual(result["gate"]["decision"], "eligible")
        self.assertEqual(result["packet"]["policy_decision"], "eligible")
        self.assertEqual(result["state"]["review"]["status"], "pass")
        self.assertTrue(
            (self.root / "packets/pr-7" / f"{HEAD_A}.json").is_file()
        )

    def test_stale_review_is_rejected_without_invalidating_current_state(self) -> None:
        self.store.apply(self.initial_event())
        result = self.store.apply(review_payload(head=OLD_HEAD))

        self.assertEqual(result["action"], "review_is_not_bound_to_current_head")
        self.assertIsNone(result["gate"])
        self.assertIsNone(result["packet"])
        self.assertIsNone(result["state"]["review"])
        rejection = json.loads(
            (self.root / "workflow-rejections/event-2.json").read_text()
        )
        self.assertEqual(rejection["reason"], "review_is_not_bound_to_current_head")

    def test_new_head_resets_pending_evidence_and_keeps_history(self) -> None:
        self.store.apply(self.initial_event())
        self.store.apply(review_payload())
        result = self.store.apply(
            self.initial_event(head=HEAD_B, event_id=3),
        )

        self.assertEqual(result["action"], "new_head_recorded")
        self.assertIsNone(result["state"]["review"])
        self.assertEqual(result["state"]["gate_decision"], "pending_review")
        self.assertTrue(
            (self.root / "pr-state/pr-7" / f"{HEAD_A}.json").is_file()
        )
        self.assertTrue(
            (self.root / "pr-state/pr-7" / f"{HEAD_B}.json").is_file()
        )
        self.assertEqual(
            json.loads((self.root / "pr-state/pr-7/current.json").read_text())[
                "head_sha"
            ],
            HEAD_B,
        )

    def test_review_before_pull_request_is_fail_closed(self) -> None:
        result = self.store.apply(review_payload())

        self.assertEqual(result["action"], "review_without_pull_request")
        self.assertIsNone(result["state"])
        self.assertIsNone(result["gate"])
        self.assertIsNone(result["packet"])
        self.assertTrue(
            (self.root / "workflow-rejections/event-2.json").is_file()
        )

    def test_verification_then_review_is_sequentially_eligible(self) -> None:
        result = self.store.apply(self.minimal_initial_event())
        self.assertEqual(result["state"]["gate_decision"], "pending_verification")

        result = self.store.apply(verification_payload(event_id=2))
        self.assertEqual(result["action"], "verification_recorded")
        self.assertEqual(result["state"]["gate_decision"], "pending_review")

        result = self.store.apply(review_payload(event_id=3))
        self.assertEqual(result["gate"]["decision"], "eligible")
        self.assertEqual(
            result["packet"]["statuses"]["asdi/policy"],
            "pass",
        )

    def test_review_before_verification_remains_pending(self) -> None:
        self.store.apply(self.minimal_initial_event())
        result = self.store.apply(review_payload(event_id=2))

        self.assertEqual(result["action"], "review_recorded_pending_verification")
        self.assertIsNone(result["gate"])
        self.assertEqual(result["state"]["gate_decision"], "pending_verification")
        self.assertIsNotNone(result["state"]["review"])

    def test_policy_status_cannot_be_verification_input(self) -> None:
        event = verification_payload()
        event["payload"]["statuses"]["asdi/policy"] = "pass"
        result = self.store.apply(event)

        self.assertEqual(
            result["action"],
            "invalid_verification_payload",
        )
        self.assertIn(
            "asdi/policy is an output and may not be an input",
            result["failures"],
        )

    def test_malformed_event_is_rejected(self) -> None:
        event = self.initial_event()
        event["payload"]["head_sha"] = "not-a-sha"
        result = self.store.apply(event)

        self.assertEqual(result["action"], "invalid_pull_request_payload")
        self.assertIsNone(result["state"])
        self.assertTrue(
            (self.root / "workflow-rejections/event-1.json").is_file()
        )
