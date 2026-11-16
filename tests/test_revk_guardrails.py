from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from launcher.runner import DockerRuntime, REVKLauncher


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "schemas/examples/run-contract.valid.json"


class HangProcess:
    returncode = None

    def poll(self) -> int:
        return None

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return "", ""


class KillTrackingRuntime(DockerRuntime):
    def __init__(self) -> None:
        self.killed = False

    def create_network(self, name: str) -> None:
        pass

    def create_volume(self, name: str) -> None:
        pass

    def populate_volume(self, volume: str, source: Path, *, destination: str = "/workspace") -> None:
        pass

    def chown_volume(self, volume: str, destination: str, ownership: str) -> None:
        pass

    def start(self, **kwargs):
        self.kwargs = kwargs
        return HangProcess()

    def kill(self, name: str) -> None:
        self.killed = True

    def copy_volume(self, volume: str, destination: Path, image: str) -> None:
        pass

    def remove_network(self, name: str) -> None:
        pass

    def remove_volume(self, name: str) -> None:
        pass


class RevKGuardrailTests(unittest.TestCase):
    def test_turn_guardrail_kills_isolated_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = root / "product"
            product.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(product)], check=True, capture_output=True)
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
            runtime = KillTrackingRuntime()
            launcher = REVKLauncher(
                root=root / "asdi",
                product_root=product,
                runtime=runtime,
                agent_script=ROOT / "launcher/agents/fixture_agent.py",
            )
            contract = json.loads(CONTRACT.read_text())
            contract["guardrails"]["minutes"] = 90
            contract["guardrails"]["turns"] = 1
            path = root / "contract.json"
            path.write_text(json.dumps(contract))
            with self.assertRaisesRegex(RuntimeError, "turn guardrail"):
                launcher.run(path)
            self.assertTrue(runtime.killed)
            self.assertIn("asdi-run-", runtime.kwargs["network"])
            self.assertNotIn("/var/run/docker.sock", str(runtime.kwargs["binds"]))
