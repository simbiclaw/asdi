from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from launcher.runner import DockerRuntime, REVKLauncher
from tests.test_revk_guardrails import KillTrackingRuntime
from tests.test_revk_runner import FakeProcess, FakeRuntime


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "schemas/examples/run-contract.valid.json"
AGENT = ROOT / "launcher/agents/fixture_agent.py"


class VerifierAuthorityTests(unittest.TestCase):
    def make_product(self, root: Path) -> Path:
        root.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
        (root / "src").mkdir()
        (root / "src" / "app.py").write_text("VALUE = 1\n")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@invalid",
                "commit",
                "-m",
                "base",
            ],
            check=True,
            capture_output=True,
        )
        return root

    def test_verify_head_requires_base_harness_and_mounts_base_volume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = self.make_product(root / "product")
            base_export = root / "base"
            base_export.mkdir()
            verify_dir = base_export / "verify" / "bin"
            verify_dir.mkdir(parents=True)
            fake_docker = root / "fake-docker"
            docker_log = root / "docker-arguments.log"
            fake_docker.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" >> {docker_log}\nexit 0\n")
            fake_docker.chmod(0o755)
            runtime = FakeRuntime(root / "workspace", root / "evidence")
            runtime.docker = str(fake_docker)
            launcher = REVKLauncher(
                root=root / "asdi",
                product_root=product,
                runtime=runtime,
                agent_script=AGENT,
            )
            check = launcher._run_base_verify(
                run_id="r-fixture",
                base=base_export,
                workspace_volume="asdi-workspace-fixture",
                base_volume="asdi-base-fixture",
                commit="a" * 40,
            )
            self.assertEqual(check["status"], "blocked")
            self.assertIn("executable", check["stderr"])

            verify = verify_dir / "verify"
            verify.write_text("#!/bin/sh\nexit 0\n")
            verify.chmod(0o755)
            check = launcher._run_base_verify(
                run_id="r-fixture",
                base=base_export,
                workspace_volume="asdi-workspace-fixture",
                base_volume="asdi-base-fixture",
                commit="a" * 40,
            )
            self.assertEqual(check["status"], "pass")
            self.assertEqual(check["exit_code"], 0)
            invocations = docker_log.read_text().splitlines()
            self.assertTrue(invocations)
            self.assertIn(f"ASDI_COMMIT={'a' * 40}", invocations)
            self.assertFalse(
                any("destination=/opt/base:ro" in line for line in invocations)
            )
            self.assertTrue(
                all(
                    "destination=/opt/base,readonly" in line
                    for line in invocations
                    if "asdi-base-fixture" in line
                )
            )

    def test_green_verify_exit_requires_bound_caught_feature_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            evidence = workspace / ".asdi-evidence"
            evidence.mkdir()
            result_path = evidence / "result.json"
            expected = [
                ("missing", None, "error", "result.json"),
                ("wrong_run", {"schema": 2, "run_id": "r-other", "commit": "c" * 40, "features": []}, "fail", "run_id mismatch"),
                (
                    "valid",
                    {
                        "schema": 2,
                        "run_id": "r-fixture",
                        "commit": "c" * 40,
                        "features": [
                            {
                                "id": "feature:test",
                                "status": "pass",
                                "control": "caught",
                                "evidence": ["output.txt"],
                                "limits": ["fixture"],
                            }
                        ],
                    },
                    "pass",
                    None,
                ),
            ]
            for _name, value, expected_status, expected_error in expected:
                if value is None:
                    result_path.unlink(missing_ok=True)
                else:
                    result_path.write_text(json.dumps(value))
                verify_check = {"id": "verify:base-harness", "status": "pass"}
                verifier_result = {}
                REVKLauncher._collect_verify_result(
                    workspace=workspace,
                    run_id="r-fixture",
                    commit="c" * 40,
                    verify_check=verify_check,
                    verifier_result=verifier_result,
                )
                self.assertEqual(verify_check["status"], expected_status)
                if expected_error:
                    self.assertIn(expected_error, verify_check["stderr"])
            self.assertEqual(verifier_result["features"][0]["id"], "feature:test")

    def test_successful_agent_cannot_overturn_red_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = KillTrackingRuntime()
            runtime.start = lambda **kwargs: (setattr(runtime, "kwargs", kwargs), FakeProcess())[-1]
            runtime.remove_container = lambda name: None
            launcher = REVKLauncher(
                root=Path(temporary) / "asdi",
                product_root=Path(temporary) / "product",
                runtime=runtime,
                agent_script=AGENT,
            )
            self.make_product(Path(temporary) / "product")
            launcher._verify_head = lambda **kwargs: [
                {"id": "static:forced-red", "status": "fail", "exit_code": 1}
            ]
            result = launcher.run(CONTRACT)
            self.assertEqual(result.status, "failed")
            self.assertEqual(runtime.kwargs["image"], "safeclaw:cc-2.1.283")

    def test_base_harness_snapshot_ignores_agent_weakening(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            product = self.make_product(Path(temporary) / "product")
            verify = product / "verify" / "bin"
            verify.mkdir(parents=True)
            (verify / "verify").write_text("#!/bin/sh\nexit 0\n")
            (product / "src" / "app.py").write_text("VALUE = 1\n")
            subprocess.run(["git", "-C", str(product), "add", "."], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(product),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@invalid",
                    "commit",
                    "-m",
                    "base",
                ],
                check=True,
                capture_output=True,
            )
            runtime = FakeRuntime(Path(temporary) / "workspace", Path(temporary) / "evidence")
            launcher = REVKLauncher(
                root=Path(temporary) / "asdi",
                product_root=product,
                base_branch="main",
                runtime=runtime,
                agent_script=AGENT,
            )
            runtime.start = lambda **kwargs: self.weaken_and_return_process(runtime.workspace)
            launcher._fresh_export(launcher.runs_root / "r-fixture" / "workspace")
            exported = launcher.runs_root / "r-fixture" / "workspace" / "verify" / "bin" / "verify"
            self.assertIn("exit 0", exported.read_text())
            # Agent mutates the same trusted path after launch; the Phase 1 base export must not change.
            exported.write_text("#!/bin/sh\nexit 101\n")
            launcher._fresh_export(launcher.runs_root / "r-fixture" / "workspace")
            self.assertIn("exit 0", exported.read_text())

    def weaken_and_return_process(self, workspace: Path) -> FakeProcess:
        (workspace / "verify" / "bin").mkdir(parents=True, exist_ok=True)
        (workspace / "verify" / "bin" / "verify").write_text("#!/bin/sh\nexit 101\n")
        return FakeProcess()

    def test_run_environment_has_no_model_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            product = self.make_product(Path(temporary) / "product")
            runtime = FakeRuntime(Path(temporary) / "workspace", Path(temporary) / "evidence")
            launcher = REVKLauncher(
                root=Path(temporary) / "asdi",
                product_root=Path(temporary) / "product",
                runtime=runtime,
                agent_script=AGENT,
            )
            launcher._verify_head = lambda **kwargs: []
            launcher.run(CONTRACT)
            environment = runtime.kwargs["environment"]
            for key in environment:
                self.assertNotIn("API_KEY", key.upper())
                self.assertNotIn("TOKEN", key.upper())
