"""Blue/green deploy, smoke rollback and production-boundary tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from ci.approval import ApprovalError, write_json_atomic
from deploy.config import DEFAULT_LIMITS_PATH, load_prod_limits
from deploy.deployer import (
    PROD_NETWORK,
    DeployError,
    _reject_unsafe_run_command,
    build_run_command,
    deploy,
)
from tests.test_phase7_support import (
    COMMIT,
    DIGEST,
    PRIOR_DIGEST,
    REGISTRY,
    FakeDockerRunner,
    read_json,
    write_decision,
)


def passing_smoke(port: int) -> dict[str, Any]:
    return {
        "healthz": {"status": "ok"},
        "readyz": {"status": "ready"},
        "notes": {"notes": []},
    }


class Phase7DeployTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="asdi-phase7-deploy-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state_dir = self.root / "state"
        self.decision = write_decision(self.root / "decision.json", COMMIT)

    def deploy_once(
        self,
        runner: FakeDockerRunner,
        digest: str,
        run_id: str,
        smoke: Any = passing_smoke,
        **overrides: Any,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "commit": COMMIT,
            "digest": digest,
            "decision_file": self.decision,
            "registry": REGISTRY,
            "state_dir": self.state_dir,
            "runner": runner,
            "smoke": smoke,
            "run_id": run_id,
            "deployed_at": "2026-11-20T00:00:00Z",
        }
        arguments.update(overrides)
        return deploy(**arguments)

    def test_missing_approval_is_refused_before_any_docker_command(self) -> None:
        runner = FakeDockerRunner()
        with self.assertRaisesRegex(ApprovalError, "missing"):
            self.deploy_once(runner, DIGEST, "no-approval", decision_file=self.root / "absent.json")
        self.assertEqual(runner.commands, [])

    def test_failed_approval_is_refused(self) -> None:
        failed = write_decision(self.root / "failed.json", COMMIT, passed=False)
        with self.assertRaisesRegex(ApprovalError, "did not pass"):
            self.deploy_once(FakeDockerRunner(), DIGEST, "failed", decision_file=failed)

    def test_successful_deploy_swaps_pointer_to_new_digest(self) -> None:
        runner = FakeDockerRunner()
        first = self.deploy_once(runner, PRIOR_DIGEST, "first")
        self.assertEqual(first["status"], "deployed")
        self.assertEqual(read_json(self.state_dir / "active.json")["slot"], "blue")

        second = self.deploy_once(runner, DIGEST, "second")
        self.assertEqual(second["status"], "deployed")
        pointer = read_json(self.state_dir / "active.json")
        self.assertEqual(pointer["digest"], DIGEST)
        self.assertEqual(pointer["slot"], "green")
        state = read_json(self.state_dir / "state.json")
        self.assertEqual(state["active_digest"], DIGEST)
        self.assertEqual(state["history"][-1]["event"], "swap")
        self.assertIn(("pull", f"{REGISTRY}@{DIGEST}"), runner.commands)

    def test_failed_smoke_rolls_back_to_previous_digest(self) -> None:
        runner = FakeDockerRunner()
        first = self.deploy_once(runner, PRIOR_DIGEST, "first")
        self.assertEqual(first["status"], "deployed")

        def failing_smoke(port: int) -> dict[str, Any]:
            raise RuntimeError("synthetic smoke failure")

        rolled_back = self.deploy_once(runner, DIGEST, "bad", smoke=failing_smoke)
        self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertEqual(rolled_back["active_digest"], PRIOR_DIGEST)
        self.assertEqual(read_json(self.state_dir / "active.json")["digest"], PRIOR_DIGEST)
        self.assertEqual(read_json(self.state_dir / "state.json")["active_digest"], PRIOR_DIGEST)
        self.assertTrue(
            any(
                command[:3] == ("rm", "--force", "toy-notes-green-bad")
                for command in runner.commands
            )
        )

    def test_smoke_failure_without_previous_digest_keeps_pointer_absent(self) -> None:
        def failing_smoke(port: int) -> dict[str, Any]:
            raise RuntimeError("no service")

        record = self.deploy_once(FakeDockerRunner(), DIGEST, "first", smoke=failing_smoke)
        self.assertEqual(record["status"], "rolled_back")
        self.assertIsNone(record["active_digest"])
        self.assertFalse((self.state_dir / "active.json").exists())

    def test_run_command_is_prod_only_without_socket_or_secrets(self) -> None:
        command = build_run_command(
            registry=REGISTRY,
            digest=DIGEST,
            commit=COMMIT,
            container_name="toy-notes-blue-test",
            port=34567,
            run_id="test",
            limits=load_prod_limits(DEFAULT_LIMITS_PATH),
        )
        self.assertIn("--network", command)
        self.assertIn(PROD_NETWORK, command)
        self.assertIn("--oom-score-adj", command)
        self.assertEqual(command[command.index("--oom-score-adj") + 1], "-500")
        self.assertIn("8g", command)
        self.assertIn(f"{REGISTRY}@{DIGEST}", command)
        joined = " ".join(command).lower()
        self.assertNotIn("/var/run/docker.sock", joined)
        self.assertNotIn("--privileged", joined)
        self.assertNotIn("agent", joined)
        self.assertNotIn("staging", joined)
        for token in ("token", "secret", "password", "api_key", "credential"):
            self.assertNotIn(token, joined)

    def test_build_record_mismatch_is_refused(self) -> None:
        mismatched = write_json_atomic(
            self.root / "build-record.json",
            {
                "schema_version": "asdi.phase7-build-record/v1",
                "commit": COMMIT,
                "digest": PRIOR_DIGEST,
            },
        )
        with self.assertRaisesRegex(ApprovalError, "different digest"):
            self.deploy_once(
                FakeDockerRunner(), DIGEST, "mismatch", build_record_file=mismatched
            )

    def test_digest_format_is_validated(self) -> None:
        with self.assertRaises(ApprovalError):
            self.deploy_once(FakeDockerRunner(), "latest", "bad-digest")

    def test_prod_limits_come_from_config_seam(self) -> None:
        self.assertEqual(load_prod_limits(DEFAULT_LIMITS_PATH).oom_score_adj, -500)
        self.assertEqual(load_prod_limits(DEFAULT_LIMITS_PATH).memory, "8g")

    def test_unsafe_run_command_is_rejected(self) -> None:
        command = build_run_command(
            registry=REGISTRY,
            digest=DIGEST,
            commit=COMMIT,
            container_name="safe",
            port=34567,
            run_id="test",
            limits=load_prod_limits(),
        )
        with self.assertRaisesRegex(DeployError, "unsafe"):
            _reject_unsafe_run_command([*command, "--privileged"])


if __name__ == "__main__":
    unittest.main()
