from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from launcher.runner import DockerRuntime, REVKLauncher


ROOT = Path(__file__).resolve().parents[1]


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = 0

    def poll(self) -> int:
        return 0

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return "fixture complete\n", ""


class FakeRuntime(DockerRuntime):
    def __init__(self, workspace: Path, evidence: Path) -> None:
        self.workspace = workspace
        self.evidence = evidence
        self.started = False

    def create_network(self, name: str) -> None:
        self.network = name

    def create_volume(self, name: str) -> None:
        self.volume = name

    def populate_volume(self, volume: str, source: Path, *, destination: str = "/workspace") -> None:
        self.populated = (volume, source, destination)

    def chown_volume(self, volume: str, destination: str, ownership: str) -> None:
        self.ownership = (volume, destination, ownership)

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
            result = launcher.run(ROOT / "schemas/examples/run-contract.valid.json")
            self.assertEqual(result.status, "succeeded")
            self.assertTrue(runtime.started)
            self.assertTrue(runtime.removed_network)
            self.assertTrue(runtime.removed_volume)
            self.assertFalse(runtime.kwargs["environment"].get("LITELLM_API_KEY"))
            self.assertNotIn("/var/run/docker.sock", str(runtime.kwargs["binds"]))
            self.assertTrue(result.evidence["valid"])
            self.assertEqual(runtime.populated[0], runtime.volume)
            expected_workspace = root / "asdi" / "runs" / result.run_id / "workspace"
            self.assertEqual(runtime.populated[1].resolve(), expected_workspace.resolve())
            self.assertTrue((expected_workspace / "src" / "notes.py").is_file())
