from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from events.classifier import classify_changed_paths
from events.journal import EventJournal, LocalPoller, PollerState
from events.pr_gate import PRGate, deployment_decision, post_merge_check


CLASS_CONFIG = {
    "judgment_paths": ["src/auth/**"],
    "agent_mergeable_paths": ["src/**"],
}
FEATURE_MAP = {
    "notes": ["src/**"],
}


class PollerTests(unittest.TestCase):
    def test_events_survive_offline_and_catch_up_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            journal = EventJournal(root)
            state = PollerState(root)
            poller = LocalPoller(journal=journal, state=state)
            processed: list[int] = []

            first = poller.catch_up(
                handler=lambda event: processed.append(event["event_id"]),
                now=100.0,
            )
            self.assertEqual(first["processed"], 0)
            journal.append(event_type="github.pull_request", payload={"pr": 1})
            journal.append(event_type="github.pull_request", payload={"pr": 2})
            health = poller.health(now=101.0)
            self.assertFalse(health["healthy"])
            self.assertEqual(health["alert"], "poller_backlog")

            second = poller.catch_up(
                handler=lambda event: processed.append(event["event_id"]),
                now=102.0,
            )
            self.assertEqual(second["processed"], 2)
            self.assertEqual(processed, [1, 2])
            self.assertTrue(poller.health(now=103.0)["healthy"])

            third = poller.catch_up(
                handler=lambda event: processed.append(event["event_id"]),
                now=104.0,
            )
            self.assertEqual(third["processed"], 0)
            self.assertEqual(processed, [1, 2])

    def test_stale_poller_alerts_after_configured_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            journal = EventJournal(Path(temporary))
            state = PollerState(Path(temporary))
            poller = LocalPoller(
                journal=journal,
                state=state,
                stale_after_seconds=10,
            )
            poller.catch_up(handler=lambda event: None, now=100.0)
            health = poller.health(now=111.0)
            self.assertFalse(health["healthy"])
            self.assertEqual(health["alert"], "poller_stale")


class ClassifierTests(unittest.TestCase):
    def test_uncovered_path_requires_human(self) -> None:
        result = classify_changed_paths(
            paths=["src/new.py"],
            feature_map={"notes": ["src/old.py"]},
            class_config=CLASS_CONFIG,
        )
        self.assertEqual(result["decision"], "human_required")
        self.assertIn("uncovered-product-path", result["rules_fired"])

    def test_judgment_path_requires_human(self) -> None:
        result = classify_changed_paths(
            paths=["src/auth/token.py"],
            feature_map={"notes": ["src/**"]},
            class_config=CLASS_CONFIG,
        )
        self.assertEqual(result["decision"], "human_required")
        self.assertEqual(result["explicit_judgment_paths"], ["src/auth/token.py"])


class PRGateTests(unittest.TestCase):
    def valid_payload(self, head: str) -> dict:
        return {
            "pr_number": 7,
            "head_sha": head,
            "base_ref": "main",
            "changed_paths": ["src/feature.py"],
            "statuses": {"ci": "pass", "asdi/policy": "pass"},
            "verifier": {"candidate_commit": head, "status": "pass"},
            "review": {"reviewed_commit": head, "passed": True},
        }

    def test_eligible_packet_is_durable_shape(self) -> None:
        gate = PRGate(class_config=CLASS_CONFIG, feature_map=FEATURE_MAP)
        result = gate.evaluate(self.valid_payload("a" * 40))
        self.assertEqual(result["decision"], "eligible")
        self.assertFalse(result["human_required"])
        self.assertEqual(result["packet"]["policy_decision"], "eligible")
        json.dumps(result["packet"])

    def test_verification_product_mix_requires_split(self) -> None:
        payload = self.valid_payload("b" * 40)
        payload["changed_paths"] = ["src/feature.py", ".asdi/static-gates.yaml"]
        gate = PRGate(class_config=CLASS_CONFIG, feature_map=FEATURE_MAP)
        result = gate.evaluate(payload)
        self.assertEqual(result["decision"], "split_required")
        self.assertTrue(result["split_required"])

    def test_new_head_invalidates_review_and_verifier(self) -> None:
        gate = PRGate(class_config=CLASS_CONFIG, feature_map=FEATURE_MAP)
        payload = self.valid_payload("c" * 40)
        payload["review"]["reviewed_commit"] = "old"
        payload["verifier"]["candidate_commit"] = "old"
        result = gate.evaluate(payload)
        self.assertEqual(result["decision"], "blocked")
        self.assertIn("review is not bound to PR head", result["failures"])
        self.assertIn("verifier is not bound to PR head", result["failures"])


class PostMergeTests(unittest.TestCase):
    def test_failed_main_requires_auto_revert_and_blocks_deploy(self) -> None:
        commit = "d" * 40
        result = post_merge_check(
            payload={
                "commit": commit,
                "statuses": {"ci": "fail"},
                "verifier": {"candidate_commit": commit, "status": "fail"},
            }
        )
        self.assertFalse(result["deployment_eligible"])
        self.assertEqual(result["auto_revert"]["reverted_commit"], commit)
        deployment = deployment_decision(commit=commit, main_results=[result])
        self.assertFalse(deployment["eligible"])

    def test_exact_passing_main_result_allows_deploy(self) -> None:
        commit = "e" * 40
        result = post_merge_check(
            payload={
                "commit": commit,
                "statuses": {"ci": "pass"},
                "verifier": {"candidate_commit": commit, "status": "pass"},
            }
        )
        self.assertTrue(result["deployment_eligible"])
        deployment = deployment_decision(commit=commit, main_results=[result])
        self.assertTrue(deployment["eligible"])

    def test_old_result_does_not_authorize_new_commit(self) -> None:
        result = post_merge_check(
            payload={
                "commit": "f" * 40,
                "statuses": {"ci": "pass"},
                "verifier": {"candidate_commit": "f" * 40, "status": "pass"},
            }
        )
        deployment = deployment_decision(commit="0" * 40, main_results=[result])
        self.assertFalse(deployment["eligible"])
