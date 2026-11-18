from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from launcher.agent_adapters import ADAPTERS, adapter_script
from launcher.runner import REVKLauncher
from tests.test_revk_runner import FakeRuntime


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "schemas/examples/run-contract.valid.json"


class AgentAdapterTests(unittest.TestCase):
    def test_registry_is_explicit_and_board_neutral(self) -> None:
        self.assertEqual(
            list(ADAPTERS),
            ["fixture", "claude"],
        )
        self.assertEqual(ADAPTERS["claude"].stream_format, "stream-json")
        with self.assertRaises(ValueError):
            adapter_script(ROOT / "launcher/agents", "paperclip")

    def test_claude_adapter_resolves_to_dedicated_script(self) -> None:
        script = adapter_script(ROOT / "launcher/agents", "claude")
        self.assertEqual(script.name, "claude_adapter.py")
        self.assertTrue(script.is_file())
        completed = subprocess.run(
            ["/usr/bin/python3", str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--stop-hook", completed.stdout)

    def test_runner_binds_selected_adapter_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = root / "product"
            product.mkdir()
            subprocess.run(
                ["git", "init", "-b", "main", str(product)],
                check=True,
                capture_output=True,
            )
            (product / "README.md").write_text("fixture\n")
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
            runtime = FakeRuntime(root / "workspace", root / "evidence")
            launcher = REVKLauncher(
                root=root / "asdi",
                product_root=product,
                runtime=runtime,
                agent_adapter="claude",
            )
            launcher._verify_head = lambda **kwargs: [
                {"id": "static:forced-red", "status": "fail", "blocking": True}
            ]
            result = launcher.run(CONTRACT)
            self.assertEqual(result.status, "failed")
            self.assertTrue(runtime.started)
            self.assertIn("claude_adapter.py", runtime.kwargs["binds"][1])
            environment = runtime.kwargs["environment"]
            self.assertEqual(environment["ASDI_OBJECTIVE"], "Add CSV export to the notes CLI")
            for name in environment:
                self.assertNotIn("KEY", name.upper())
                self.assertNotIn("TOKEN", name.upper())
