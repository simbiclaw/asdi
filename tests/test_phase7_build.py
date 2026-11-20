"""Fail-closed CI build tests for REV K Phase 7."""

from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from ci.approval import ApprovalError
from ci.build import build_image, main
from tests.test_phase7_support import (
    COMMIT,
    DIGEST,
    PRIOR_COMMIT,
    REGISTRY,
    FakeDockerRunner,
    read_json,
    write_decision,
)


class Phase7BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="asdi-phase7-build-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.decision = write_decision(self.root / "decision.json", COMMIT)
        self.artifact = self.root / "image.tar"
        self.record = self.root / "build-record.json"

    def build(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "commit": COMMIT,
            "decision_file": self.decision,
            "registry": REGISTRY,
            "artifact_path": self.artifact,
            "record_path": self.record,
            "runner": FakeDockerRunner(),
            "built_at": "2026-11-20T00:00:00Z",
        }
        arguments.update(overrides)
        result = build_image(**arguments)  # type: ignore[arg-type]
        return result

    def test_missing_decision_is_refused(self) -> None:
        self.decision.unlink()
        with self.assertRaisesRegex(ApprovalError, "missing"):
            self.build()

    def test_stale_decision_is_refused(self) -> None:
        stale = write_decision(self.root / "stale.json", PRIOR_COMMIT)
        with self.assertRaisesRegex(ApprovalError, "stale"):
            self.build(decision_file=stale)

    def test_failed_main_result_is_refused(self) -> None:
        failed = write_decision(self.root / "failed.json", COMMIT, passed=False)
        with self.assertRaisesRegex(ApprovalError, "did not pass"):
            self.build(decision_file=failed)

    def test_required_revert_is_refused(self) -> None:
        reverted = write_decision(self.root / "revert.json", COMMIT, auto_revert=True)
        with self.assertRaisesRegex(ApprovalError, "auto-revert"):
            self.build(decision_file=reverted)

    def test_exact_commit_is_required(self) -> None:
        with self.assertRaisesRegex(ApprovalError, "40-character"):
            self.build(commit=COMMIT[:12])

    def test_successful_build_records_commit_digest_artifact_and_approval(self) -> None:
        runner = FakeDockerRunner()
        record = self.build(runner=runner)
        self.assertEqual(record["commit"], COMMIT)
        self.assertEqual(record["digest"], DIGEST)
        expected_artifact_digest = "sha256:" + hashlib.sha256(b"fake-oci-archive").hexdigest()
        self.assertEqual(record["artifact_digest"], expected_artifact_digest)
        self.assertEqual(record["approval"]["source"], "main")
        self.assertEqual(record["approval"]["commit"], COMMIT)
        self.assertEqual(record["approval"]["post_merge"]["passed"], True)
        self.assertEqual(read_json(self.record)["digest"], DIGEST)
        self.assertTrue(Path(str(record["record_path"])).is_file())
        self.assertTrue(
            any(command[:3] == ("buildx", "build", "--network=none") for command in runner.commands)
        )
        self.assertTrue(any("push" in arg for command in runner.commands for arg in command))
        self.assertIn(("pull", f"{REGISTRY}@{DIGEST}"), runner.commands)

    def test_cli_exits_two_without_approval(self) -> None:
        arguments = [
            "--commit",
            COMMIT,
            "--decision-file",
            str(self.root / "absent.json"),
            "--registry",
            REGISTRY,
            "--artifact",
            str(self.artifact),
            "--record",
            str(self.record),
        ]
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(arguments)
        self.assertEqual(code, 2)
        self.assertIn("build refused", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
