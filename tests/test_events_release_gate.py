from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from events.cli import main
from events.main_workflow import MainWorkflowStore
from events.release_gate import release_readiness


COMMIT = "a" * 40
NEXT_COMMIT = "b" * 40
ARTIFACT = "sha256:" + "c" * 64


def push(commit: str = COMMIT, event_id: int = 1) -> dict:
    return {
        "event_id": event_id,
        "event_type": "github.push",
        "payload": {"branch": "main", "commit": commit},
    }


def verification(commit: str = COMMIT, event_id: int = 2, status: str = "pass") -> dict:
    return {
        "event_id": event_id,
        "event_type": "github.main_verification_completed",
        "payload": {
            "commit": commit,
            "statuses": {"ci": status},
            "verifier": {
                "candidate_commit": commit,
                "status": status,
                "manifest_id": "m-main",
                "run_id": "r-main",
            },
        },
    }


class ReleaseReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = MainWorkflowStore(self.root / "main-workflow")
        self.store.apply(push())
        self.store.apply(verification())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def evaluate(self, **overrides) -> dict:
        arguments = {
            "commit": COMMIT,
            "artifact_digest": ARTIFACT,
            "main_state": self.store.current_state(COMMIT),
            "current_state": self.store.current_state(),
        }
        arguments.update(overrides)
        return release_readiness(**arguments)

    def test_exact_passing_main_and_artifact_are_ready_but_human_gated(self) -> None:
        result = self.evaluate()
        self.assertEqual(result["decision"], "ready")
        self.assertTrue(result["deployment_eligible"])
        self.assertTrue(result["human_required"])
        self.assertFalse(result["release_executed"])
        self.assertEqual(result["artifact_digest"], ARTIFACT)

    def test_stale_commit_is_blocked(self) -> None:
        self.store.apply(push(NEXT_COMMIT, event_id=3))
        result = self.evaluate()
        self.assertEqual(result["decision"], "blocked")
        self.assertIn("release commit is no longer current main", result["failures"])

    def test_failed_post_merge_result_is_blocked(self) -> None:
        main_state = self.store.current_state(COMMIT)
        main_state["result"] = {
            "commit": COMMIT,
            "passed": False,
            "failures": ["main ci is not pass"],
            "deployment_eligible": False,
        }
        result = self.evaluate(main_state=main_state)
        self.assertEqual(result["decision"], "blocked")
        self.assertFalse(result["deployment_eligible"])
        self.assertTrue(result["human_required"])

    def test_malformed_artifact_is_blocked(self) -> None:
        result = self.evaluate(artifact_digest="latest")
        self.assertEqual(result["decision"], "blocked")
        self.assertIn("release artifact must be bound to a sha256 digest", result["failures"])

    def test_cli_persists_release_readiness_without_releasing(self) -> None:
        (self.root / "classes.json").write_text(json.dumps({
            "judgment_paths": [],
            "agent_mergeable_paths": ["src/**"],
        }))
        (self.root / "coverage.json").write_text(json.dumps({"notes": ["src/**"]}))
        output = self.root / "readiness.json"
        exit_code = main([
            "--root",
            str(self.root),
            "--class-config",
            str(self.root / "classes.json"),
            "--feature-map",
            str(self.root / "coverage.json"),
            "release-readiness",
            "--commit",
            COMMIT,
            "--artifact-digest",
            ARTIFACT,
            "--readiness-output",
            str(output),
        ])
        self.assertEqual(exit_code, 0)
        persisted = json.loads(output.read_text())
        self.assertEqual(persisted["decision"], "ready")
        self.assertFalse(persisted["release_executed"])
        self.assertTrue((self.root / "latest-release-readiness.json").is_file())


if __name__ == "__main__":
    unittest.main()
