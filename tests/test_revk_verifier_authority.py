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
