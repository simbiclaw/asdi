from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from launcher.runner import DockerRuntime, REVKLauncher


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "schemas/examples/run-contract.valid.json"


class TurnOutputProcess:
    def __init__(self, events: list[str]) -> None:
        self.returncode = None
        self.stdout = iter(events)

    def poll(self) -> int:
        return None

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return "", ""


class KillTrackingRuntime(DockerRuntime):
    def __init__(self) -> None:
        self.killed = False
        self.started = False
        self.process_events = [
            '{"event":"turn","turn":1}\n',
            '{"event":"turn","turn":2}\n',
            '{"event":"usage","tokens":1,"usd":0}\n',
        ]

    def start(self, **kwargs):
        self.started = True
        self.kwargs = kwargs
        return __import__("tests.test_revk_runner", fromlist=["FakeProcess"]).FakeProcess()

    def create_network(self, name: str) -> None:
        pass

    def create_volume(self, name: str) -> None:
        pass

    def ensure_bridge_network(self, name: str) -> None:
        pass

    def populate_volume(self, volume: str, source: Path, *, destination: str = "/workspace") -> None:
        pass

    def chown_volume(self, volume: str, destination: str, ownership: str) -> None:
        pass

    def start_proxy(self, **kwargs) -> None:
        self.proxy_kwargs = kwargs

    def connect_network(self, container: str, network: str) -> None:
        self.proxy_network = (container, network)

    def stop_proxy(self, name: str) -> None:
        self.stopped_proxy = name

    def start(self, **kwargs):
        self.kwargs = kwargs
        return TurnOutputProcess(self.process_events)

    def kill(self, name: str) -> None:
        self.killed = True

    def inspect_image(self, image: str) -> str:
        return f"sha256:{image}"

    def copy_volume(self, volume: str, destination: Path, image: str) -> None:
        pass

    def remove_network(self, name: str) -> None:
        pass

    def remove_volume(self, name: str) -> None:
        pass


class RevKGuardrailTests(unittest.TestCase):
    def make_product(self, root: Path) -> Path:
        root.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
        (root / "README.md").write_text("fixture\n")
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

    def make_launcher(self, root: Path, product: Path, runtime: KillTrackingRuntime) -> REVKLauncher:
        return REVKLauncher(
            root=root / "asdi",
            product_root=product,
            runtime=runtime,
            agent_script=ROOT / "launcher/agents/fixture_agent.py",
        )

    def write_contract(self, root: Path, changes: dict) -> Path:
        contract = json.loads(CONTRACT.read_text())
        contract["guardrails"].update(changes)
        path = root / "contract.json"
        path.write_text(json.dumps(contract))
        return path

    def test_turn_guardrail_kills_isolated_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = KillTrackingRuntime()
            product = self.make_product(root / "product")
            launcher = self.make_launcher(root, product, runtime)
            path = self.write_contract(root, {"minutes": 90, "turns": 1})
            with self.assertRaisesRegex(RuntimeError, "turn guardrail"):
                launcher.run(path)
            self.assertIn("asdi-run-", runtime.kwargs["network"])
            self.assertNotIn("/var/run/docker.sock", str(runtime.kwargs["binds"]))

    def test_spend_guardrail_blocks_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = self.make_product(root / "product")
            runtime = KillTrackingRuntime()
            launcher = self.make_launcher(root, product, runtime)
            launcher.agent_default_cost_usd = 2.0
            path = self.write_contract(
                root,
                {"minutes": 90, "spend_usd": 1.0, "turns": 2},
            )
            with self.assertRaisesRegex(RuntimeError, "spend guardrail"):
                launcher.run(path)
            self.assertFalse(runtime.started)

    def test_runtime_token_guardrail_kills_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = self.make_product(root / "product")
            runtime = KillTrackingRuntime()
            runtime.process_events = ['{"event":"usage","tokens":1,"usd":0}\n']
            launcher = self.make_launcher(root, product, runtime)
            path = self.write_contract(
                root,
                {"minutes": 90, "tokens": 0, "turns": 10},
            )
            with self.assertRaisesRegex(RuntimeError, "token guardrail"):
                launcher.run(path)
            self.assertTrue(runtime.killed)

    def test_runtime_spend_guardrail_kills_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = self.make_product(root / "product")
            runtime = KillTrackingRuntime()
            runtime.process_events = ['{"event":"usage","tokens":1,"usd":0.01}\n']
            launcher = self.make_launcher(root, product, runtime)
            path = self.write_contract(
                root,
                {"minutes": 90, "spend_usd": 0.0, "tokens": 100, "turns": 10},
            )
            with self.assertRaisesRegex(RuntimeError, "spend guardrail"):
                launcher.run(path)
            self.assertTrue(runtime.killed)

    def test_wall_clock_guardrail_kills_hanging_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = self.make_product(root / "product")
            runtime = KillTrackingRuntime()
            runtime.process_events = []
            launcher = self.make_launcher(root, product, runtime)
            path = self.write_contract(
                root,
                {"minutes": 1, "tokens": 100, "turns": 10},
            )
            clock = {"now": 1000.0}

            def advance_clock() -> float:
                clock["now"] += 61.0
                return clock["now"]

            with patch("launcher.runner.time.time", advance_clock):
                with self.assertRaisesRegex(RuntimeError, "wall-clock guardrail"):
                    launcher.run(path)
            self.assertTrue(runtime.killed)

    def test_verifier_command_has_no_model_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = self.make_product(root / "product")
            base = root / "base"
            verify_dir = base / "verify" / "bin"
            verify_dir.mkdir(parents=True)
            recorded = root / "docker-arguments.txt"
            fake_docker = root / "fake-docker"
            fake_docker.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{recorded}'\n")
            fake_docker.chmod(0o755)
            verify = verify_dir / "verify"
            verify.write_text("#!/bin/sh\nexit 0\n")
            verify.chmod(0o755)
            runtime = KillTrackingRuntime()
            runtime.docker = str(fake_docker)
            launcher = self.make_launcher(root, product, runtime)
            check = launcher._run_base_verify(
                run_id="r-fixture",
                base=base,
                base_volume="asdi-base-fixture",
            )
            self.assertEqual(check["status"], "pass")
            arguments = recorded.read_text()
            self.assertNotIn("API_KEY", arguments.upper())
            self.assertNotIn("TOKEN", arguments.upper())
