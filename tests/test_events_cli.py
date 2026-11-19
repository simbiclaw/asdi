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

    def test_merge_dry_run_persists_human_authority_decision(self) -> None:
        packet_path = self.root / "packet.json"
        result_path = self.root / "merge-dry-run.json"
        self.write_json(
            packet_path,
            {
                "schema_version": "asdi.pr-packet/v1",
                "pr_number": 9,
                "head_sha": "c" * 40,
                "policy_decision": "eligible",
                "statuses": {"ci": "pass", "asdi/policy": "pass"},
                "classification": {"change_class": "agent_mergeable"},
            },
        )
        exit_code = main(
            [
                *self.common,
                "merge-dry-run",
                "--packet",
                str(packet_path),
                "--actor",
                "merge-bot",
                "--trm-level",
                "T0",
                "--result-output",
                str(result_path),
            ]
        )
        self.assertEqual(exit_code, 0)
        result = json.loads(result_path.read_text())
        self.assertEqual(result["decision"], "human_required")
        self.assertTrue(result["human_required"])
        self.assertFalse(result["merge_executed"])
        self.assertTrue((self.root / "latest-merge-dry-run.json").is_file())

    def test_review_command_executes_explicit_reviewer(self) -> None:
        head = "d" * 40
        packet_path = self.root / "review-packet.json"
        diff_path = self.root / "changed.diff"
        reviewer_path = self.root / "reviewer.py"
        result_path = self.root / "review-result.json"
        self.write_json(packet_path, {"head_sha": head, "changed_paths": ["src/x"]})
        diff_path.write_text("changed\n")
        reviewer_path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            "packet = json.loads(Path(sys.argv[1]).read_text())\n"
            "Path(sys.argv[3]).write_text(json.dumps({\n"
            "    'schema_version': 'asdi.review-result/v1',\n"
            "    'pass': 'review',\n"
            "    'model': 'local-review-model',\n"
            "    'independent_family': False,\n"
            "    'reviewed_commit': packet['head_sha'],\n"
            "    'status': 'pass',\n"
            "    'findings': [],\n"
            "}))\n"
        )
        reviewer_path.chmod(0o755)
        exit_code = main(
            [
                *self.common,
                "review",
                "--packet",
                str(packet_path),
                "--diff",
                str(diff_path),
                "--reviewer",
                "/usr/bin/python3",
                "--reviewer",
                str(reviewer_path),
                "--reviewer",
                "{packet}",
                "--reviewer",
                "{diff}",
                "--reviewer",
                "{output}",
                "--name",
                "local_review",
                "--independent-family",
                "false",
                "--result-output",
                str(result_path),
            ]
        )
        self.assertEqual(exit_code, 0)
        result = json.loads(result_path.read_text())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["reviewed_commit"], head)
        self.assertTrue((self.root / "latest-review.json").is_file())
