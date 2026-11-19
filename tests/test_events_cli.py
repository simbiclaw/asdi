from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from events.cli import main


class EventsCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.feature_map = self.root / "feature-map.json"
        self.class_config = self.root / "classes.json"
        self.feature_map.write_text(json.dumps({"notes": ["src/**"]}))
        self.class_config.write_text(
            json.dumps(
                {
                    "judgment_paths": ["src/auth/**"],
                    "agent_mergeable_paths": ["src/**"],
                }
            )
        )
        self.common = [
            "--root",
            str(self.root),
            "--class-config",
            str(self.class_config),
            "--feature-map",
            str(self.feature_map),
        ]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n")

    def test_append_catch_up_health_and_gate_are_durable(self) -> None:
        head = "a" * 40
        payload = self.root / "pull-request.json"
        self.write_json(
            payload,
            {
                "pr_number": 9,
                "head_sha": head,
                "base_ref": "main",
                "changed_paths": ["src/feature.py"],
                "statuses": {"ci": "pass", "asdi/policy": "pass"},
                "verifier": {"candidate_commit": head, "status": "pass"},
                "review": {"reviewed_commit": head, "passed": True},
            },
        )
        exit_code = main(
            [
                *self.common,
                "append-event",
                "--event-type",
                "github.pull_request",
                "--payload",
                str(payload),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue((self.root / "journal/events.jsonl").is_file())

        exit_code = main(
            [
                *self.common,
                "catch-up",
                "--now",
                "100",
            ]
        )
        self.assertEqual(exit_code, 0)
        packet_name = f"pr-9-{head[:12]}.json"
        packet_path = self.root / "packets" / packet_name
        self.assertTrue(packet_path.is_file())
        packet = json.loads(packet_path.read_text())
        self.assertEqual(packet["policy_decision"], "eligible")
        self.assertTrue((self.root / "latest-policy.json").is_file())

        health_path = self.root / "poller-health.json"
        exit_code = main(
            [
                *self.common,
                "health",
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(health_path.is_file())

    def test_post_merge_and_deployment_commands_persist_decisions(self) -> None:
        commit = "b" * 40
        payload = self.root / "post-merge.json"
        self.write_json(
            payload,
            {
                "commit": commit,
                "statuses": {"ci": "pass"},
                "verifier": {"candidate_commit": commit, "status": "pass"},
            },
        )
        result_path = self.root / "post-merge-result.json"
        exit_code = main(
            [
                *self.common,
                "post-merge",
                "--payload",
                str(payload),
                "--result-output",
                str(result_path),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(result_path.is_file())
        self.assertTrue(json.loads(result_path.read_text())["passed"])

        results_path = self.root / "main-results.json"
        self.write_json(results_path, [json.loads(result_path.read_text())])
        decision_path = self.root / "deployment.json"
        exit_code = main(
            [
                *self.common,
                "deployment-decision",
                "--commit",
                commit,
                "--main-results",
                str(results_path),
                "--decision-output",
                str(decision_path),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(decision_path.read_text())["eligible"])
