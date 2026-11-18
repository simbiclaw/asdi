from __future__ import annotations

import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        run_id = "r-clitest"
        run_root = self.root / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": run_id,
            "status": "succeeded",
            "pid": 123456,
            "container": "fake",
            "network": "asdi-run-test",
            "evidence_volume": "asdi-evidence-test",
            "workspace_volume": "asdi-workspace-test",
            "base_volume": "asdi-base-test",
            "egress_container": "asdi-egress-test",
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
        self.removed_networks = []
        self.removed_volumes = []
        FakeDocker.instances.append(self)

    def kill(self, name: str) -> None:
        self.killed.append(name)

    def stop_proxy(self, name: str) -> None:
        self.stopped_proxies.append(name)

    def teardown_run_resources(
        self,
        *,
        network: str,
        evidence_volume: str,
        workspace_volume: str,
        base_volume: str,
    ) -> None:
        self.removed_networks.append(network)
        self.removed_volumes.extend(
            [evidence_volume, workspace_volume, base_volume]
        )


class LauncherCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.output = __import__("io").StringIO()
        FakeLauncher.instances = []
        FakeDocker.instances = []

    def tearDown(self) -> None:
        self._temporary.cleanup()

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
            state = json.loads(
                (self.root / "runs" / "r-clitest" / "launcher-state.json").read_text()
            )
            self.assertEqual(state["status"], "killed")
            runtime = FakeDocker.instances[-1]
            self.assertEqual(runtime.stopped_proxies, ["asdi-egress-test"])
            self.assertEqual(runtime.removed_networks, ["asdi-run-test"])
            self.assertEqual(
                runtime.removed_volumes,
                ["asdi-evidence-test", "asdi-workspace-test", "asdi-base-test"],
            )
