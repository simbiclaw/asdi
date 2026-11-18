from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from launcher.runner import DockerRuntime, REVKLauncher
from launcher.agents.claude_proxy_agent import secret_observation


ROOT = Path(__file__).resolve().parents[1]


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = 0
        self.stdout = None

    def poll(self) -> int:
        return 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return "fixture complete\n", ""


class FakeRuntime(DockerRuntime):
    def __init__(self, workspace: Path, evidence: Path) -> None:
        self.workspace = workspace
        self.evidence = evidence
        self.started = False
        self.populated_volumes: list[str] = []
        self.populated_sources: dict[str, Path] = {}
        self.workspace_volume: str | None = None
        self.proxies: list[dict] = []

    def create_network(self, name: str) -> None:
        self.network = name

    def create_volume(self, name: str) -> None:
        self.volume = name

    def ensure_bridge_network(self, name: str) -> None:
        self.egress_network = name

    def populate_volume(self, volume: str, source: Path, *, destination: str = "/workspace") -> None:
        self.populated = (volume, source, destination)
        self.populated_volumes.append(volume)
        self.populated_sources[volume] = source
        if destination == "/workspace":
            self.workspace_volume = volume

    def chown_volume(self, volume: str, destination: str, ownership: str) -> None:
        self.ownership = (volume, destination, ownership)

    def start_proxy(self, **kwargs) -> None:
        self.proxies.append(kwargs)

    def connect_network(self, container: str, network: str) -> None:
        self.proxy_network = (container, network)

    def stop_proxy(self, name: str) -> None:
        self.stopped_proxy = name

    def inspect_image(self, image: str) -> str:
        return f"sha256:{image}"

    def remove_container(self, name: str) -> None:
        self.removed_container = True

    def start(self, **kwargs):
        self.started = True
        self.kwargs = kwargs
        self.evidence.mkdir(parents=True, exist_ok=True)
        (self.evidence / "agent.log").write_text("fixture complete\n")
        (self.evidence / "result.json").write_text(
            json.dumps(
                {
                    "schema": 2,
                    "run_id": kwargs["environment"]["ASDI_RUN_ID"],
                    "commit": "fixture",
                    "features": [
                        {
                            "id": "generated-module",
                            "status": "pass",
                            "control": "caught",
                            "evidence": ["agent.log"],
                            "limits": ["fake runtime"],
                        }
                    ],
                }
            )
        )
        return FakeProcess()

    def copy_volume(self, volume: str, destination: Path, image: str) -> None:
        for path in self.evidence.rglob("*"):
            target = destination / path.relative_to(self.evidence)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(path.read_text())

    def remove_network(self, name: str) -> None:
        self.removed_network = True

    def remove_volume(self, name: str) -> None:
        self.removed_volume = True

    def kill(self, name: str) -> None:
        self.killed = True


class ProxyLogRuntime(DockerRuntime):
    def __init__(self) -> None:
        self.docker = "docker"
        self.log_commands: list[list[str]] = []

    def _run(self, arguments: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
        self.log_commands.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "asdi-egress /v1/messages\n", "")


import json


class REVKRunnerTests(unittest.TestCase):
    def test_isolated_run_collects_verified_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product = root / "toy-notes"
            product.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(product)], check=True, capture_output=True)
            (product / "src").mkdir()
            (product / "src" / "notes.py").write_text("VALUE = 'base'\n")
            (product / ".asdi").mkdir()
            (product / ".asdi" / "static-gates.yaml").write_text(
                "version: 1\n"
                "checks:\n"
                "  - id: compile\n"
                "    command: [\"/usr/bin/python3\", \"-m\", \"py_compile\", \"src/generated.py\"]\n"
                "    blocking: true\n"
                "    timeout_seconds: 10\n"
                "policy:\n"
                "  new_violations: reject\n"
                "  legacy_findings: track_without_expanding\n"
            )
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
            workspace = root / "workspace"
            evidence = root / "volume-evidence"
            runtime = FakeRuntime(workspace, evidence)
            launcher = REVKLauncher(
                root=root / "asdi",
                product_root=product,
                base_branch="main",
                agent_image="safeclaw:cc-2.1.283",
                runtime=runtime,
                agent_script=ROOT / "launcher/agents/fixture_agent.py",
            )
            launcher._verify_head = lambda **kwargs: [
                {"id": "static:compile", "status": "pass", "exit_code": 0}
            ]
            with patch.dict(
                "os.environ",
                {"LITELLM_MASTER_KEY": "proxy-only-test-key"},
            ):
                result = launcher.run(ROOT / "schemas/examples/run-contract.valid.json")
            self.assertEqual(result.status, "succeeded")
            self.assertTrue(runtime.started)
            self.assertTrue(runtime.removed_network)
            self.assertTrue(runtime.removed_volume)
            self.assertFalse(runtime.kwargs["environment"].get("LITELLM_API_KEY"))
            self.assertEqual(
                runtime.kwargs["environment"]["HTTP_PROXY"],
                f"http://{runtime.proxies[0]['name']}:8081",
            )
            self.assertNotIn("LITELLM_MASTER_KEY", runtime.kwargs["environment"])
            self.assertTrue(runtime.proxies[0]["environment"].get("ASDI_MODEL_API_KEY"))
            self.assertEqual(
                runtime.proxies[0]["image"],
                "safeclaw-us-egress:cc-2.1.283",
            )
            self.assertNotIn("LITELLM_MASTER_KEY", str(runtime.proxies[0]["environment"]))
            self.assertEqual(runtime.proxy_network, (runtime.proxies[0]["name"], runtime.network))
            self.assertEqual(runtime.stopped_proxy, runtime.proxies[0]["name"])
            self.assertNotIn("/var/run/docker.sock", str(runtime.kwargs["binds"]))
            self.assertTrue(result.evidence["valid"])
            self.assertEqual(runtime.populated[0], runtime.volume)
            self.assertTrue(
                any(volume.startswith("asdi-base-") for volume in runtime.populated_volumes)
            )
            expected_workspace = root / "asdi" / "runs" / result.run_id / "workspace"
            workspace_volume = runtime.workspace_volume
            self.assertEqual(
                runtime.populated_sources[workspace_volume].resolve(),
                expected_workspace.resolve(),
            )
            self.assertTrue((expected_workspace / "src" / "notes.py").is_file())

    def test_proxy_log_capture_uses_docker_only_after_agent_exit(self) -> None:
        runtime = ProxyLogRuntime()
        self.assertEqual(runtime.proxy_logs("asdi-egress-test"), "asdi-egress /v1/messages\n")
        self.assertEqual(runtime.log_commands, [["logs", "asdi-egress-test"]])
        runtime.docker = None
        self.assertEqual(runtime.proxy_logs("asdi-egress-test"), "")
        self.assertEqual(len(runtime.log_commands), 1)

    def test_claude_stop_hook_treats_any_key_name_as_forbidden(self) -> None:
        observation = secret_observation(["ASDI_RUN_ID", "LITELLM_MASTER_KEY"])
        self.assertEqual(observation["forbidden_names"], ["LITELLM_MASTER_KEY"])
        self.assertIs(observation["values_recorded"], False)
