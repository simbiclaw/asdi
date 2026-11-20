from __future__ import annotations

import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from launcher.cli import main
from launcher.runner import RunResult


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "schemas/examples/run-contract.valid.json"


class FakeLauncher:
    instances: list = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.root = kwargs["root"]
        FakeLauncher.instances.append(self)

    def run(self, contract_path: str):
        self.contract_path = Path(contract_path)
        run_id = "r-clitest"
        run_root = self.root / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": run_id,
            "status": "succeeded",
            "pid": 123456,
            "container": "fake",
            "egress_container": "asdi-egress-test",
            "network": "asdi-run-test",
            "evidence_volume": "asdi-evidence-test",
            "workspace_volume": "asdi-workspace-test",
            "base_volume": "asdi-base-test",
        }
        (run_root / "launcher-state.json").write_text(json.dumps(state))
        return RunResult(
            run_id=run_id,
            status="succeeded",
            agent_exit_code=0,
            checks=[{"id": "static:test", "status": "pass"}],
            evidence={"manifest_id": "m-test", "valid": True},
            runtime={"socket_mounted": False},
        )


class FakeDocker:
    instances: list = []

    def __init__(self, docker: str) -> None:
        self.killed = []
        self.stopped_proxies = []
        self.removed_containers = []
        self.removed_networks = []
        self.removed_volumes = []
        FakeDocker.instances.append(self)

    def kill(self, name: str) -> None:
        self.killed.append(name)

    def stop_proxy(self, name: str) -> None:
        self.stopped_proxies.append(name)

    def remove_container(self, name: str) -> None:
        self.removed_containers.append(name)

    def remove_network(self, name: str) -> None:
        self.removed_networks.append(name)

    def remove_volume(self, name: str) -> None:
        self.removed_volumes.append(name)


class LauncherCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.output = __import__("io").StringIO()
        FakeLauncher.instances = []
        FakeDocker.instances = []

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_run_accepts_positional_yaml_contract(self) -> None:
        contract = json.loads(CONTRACT.read_text())
        contract_path = self.root / "contract.yaml"
        contract_path.write_text(yaml.safe_dump(contract, sort_keys=True))
        with patch("launcher.cli.REVKLauncher", FakeLauncher), patch(
            "launcher.cli.DockerRuntime", FakeDocker
        ):
            result = main(
                [
                    "--root",
                    str(self.root),
                    "--product-root",
                    str(self.root / "product"),
                    "run",
                    str(contract_path),
                ]
            )
        self.assertEqual(result, 0)
        self.assertEqual(FakeLauncher.instances[-1].contract_path.suffix, ".yaml")
        self.assertTrue((self.root / ".current-contract.yaml").is_file())

    def test_run_status_and_kill_use_durable_state(self) -> None:
        with patch("launcher.cli.REVKLauncher", FakeLauncher), patch(
            "launcher.cli.DockerRuntime", FakeDocker
        ):
            result = main(
                [
                    "--root",
                    str(self.root),
                    "--product-root",
                    str(self.root / "product"),
                    "run",
                    "--contract",
                    str(CONTRACT),
                    "--max-turns",
                    "3",
                ]
            )
            self.assertEqual(result, 0)
            status = main(
                [
                    "--root",
                    str(self.root),
                    "--product-root",
                    str(self.root / "product"),
                    "status",
                    "--run-id",
                    "r-clitest",
                ]
            )
            self.assertEqual(status, 0)
            with patch("launcher.cli.REVKLauncher", FakeLauncher), patch(
                "launcher.cli.DockerRuntime", FakeDocker
            ):
                killed = main(
                    [
                        "--root",
                        str(self.root),
                        "--product-root",
                        str(self.root / "product"),
                        "kill",
                        "--run-id",
                        "r-clitest",
                    ]
                )
            self.assertEqual(killed, 0)
            fake_docker = FakeDocker.instances[-1]
            state = json.loads(
                (self.root / "runs" / "r-clitest" / "launcher-state.json").read_text()
            )
            self.assertEqual(state["status"], "killed")
            self.assertEqual(fake_docker.killed, ["fake"])
            self.assertEqual(fake_docker.stopped_proxies, ["asdi-egress-test"])
            self.assertEqual(fake_docker.removed_networks, ["asdi-run-test"])
            self.assertEqual(
                fake_docker.removed_volumes,
                ["asdi-evidence-test", "asdi-workspace-test", "asdi-base-test"],
            )
