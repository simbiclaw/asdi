from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from launcher.runner import DockerRuntime, REVKLauncher


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
        self.verify_result: dict | None = None
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

    def teardown_run_resources(
        self,
        *,
        network: str,
        evidence_volume: str,
        workspace_volume: str,
        base_volume: str,
    ) -> None:
        self.removed_network = True
        self.removed_volume = True
        self.removed_resources = {
            "network": network,
            "evidence_volume": evidence_volume,
            "workspace_volume": workspace_volume,
            "base_volume": base_volume,
        }

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
        source = self.populated_sources.get(volume, self.evidence)
        if volume.startswith("asdi-verify-workspace-") and self.verify_result:
            evidence_directory = destination / ".asdi-evidence"
            evidence_directory.mkdir(parents=True, exist_ok=True)
            (evidence_directory / "verifier-output.txt").write_text("observed\n")
            (evidence_directory / "result.json").write_text(json.dumps(self.verify_result))
            return
        for path in source.rglob("*"):
            target = destination / path.relative_to(source)
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
    def make_product(self, root: Path) -> tuple[Path, str]:
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
            "    command: [\"/usr/bin/python3\", \"-m\", \"py_compile\", \"src/notes.py\"]\n"
            "    blocking: true\n"
            "    timeout_seconds: 10\n"
            "policy:\n"
            "  new_violations: reject\n"
            "  legacy_findings: track_without_expanding\n"
        )
        (product / ".asdi" / "product.yaml").write_text("version: 1\nname: toy-notes\n")
        subprocess.run(["git", "-C", str(product), "add", "."], check=True, capture_output=True)
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
        commit = subprocess.run(
            ["git", "-C", str(product), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return product, commit

    def test_verifier_only_revision_has_no_agent_or_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product, commit = self.make_product(root)
            workspace = root / "workspace"
            evidence = root / "volume-evidence"
            runtime = FakeRuntime(workspace, evidence)
            expected_commit = commit
            runtime.verify_result = {
                "schema": 2,
                "run_id": "filled-by-verifier",
                "commit": commit,
                "features": [
                    {
                        "id": "feature:notes",
                        "status": "pass",
                        "control": "caught",
                        "evidence": ["verifier-output.txt"],
                        "limits": [],
                    }
                ],
            }
            launcher = REVKLauncher(
                root=root / "asdi",
                product_root=product,
                base_branch="main",
                agent_image="safeclaw:cc-2.1.283",
                runtime=runtime,
            )

            def verify_head(
                *,
                run_id: str,
                commit: str,
                workspace_volume: str,
                evidence_stage: Path,
                verifier_result,
                **kwargs,
            ):
                self.assertEqual(commit, expected_commit)
                runtime.verify_result["run_id"] = run_id
                runtime.verify_result["commit"] = commit
                self.assertTrue(workspace_volume.startswith("asdi-verify-workspace-"))
                evidence_stage.mkdir(parents=True, exist_ok=True)
                (evidence_stage / "verifier-output.txt").write_text("observed\n")
                (evidence_stage / "result.json").write_text(
                    json.dumps(
                        {
                            "schema": 2,
                            "run_id": run_id,
                            "commit": commit,
                            "features": [
                                {
                                    "id": "feature:notes",
                                    "status": "pass",
                                    "control": "caught",
                                    "evidence": ["verifier-output.txt"],
                                    "limits": [],
                                }
                            ],
                        }
                    )
                )
                verifier_result.update(
                    json.loads((evidence_stage / "result.json").read_text())
                )
                return [
                    {"id": "static:compile", "status": "pass"},
                    {"id": "verify:base-harness", "status": "pass"},
                ]

            with patch.object(launcher, "_verify_head", verify_head):
                result = launcher.verify_revision(commit)

            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["source"], "pr-head")
            self.assertEqual(result["commit"], commit)
            self.assertTrue(result["evidence"]["valid"])
            self.assertFalse(runtime.started)
            self.assertFalse(runtime.proxies)
            self.assertFalse(result["runtime"]["socket_mounted"])
            self.assertFalse(result["runtime"]["secrets_mounted"])
            self.assertFalse(result["runtime"]["agent_started"])
            self.assertEqual(result["runtime"]["network"], "none")
            self.assertTrue(runtime.removed_volume)
            state_path = (
                root / "asdi" / "runs" / result["run_id"] / "launcher-state.json"
            )
            state = json.loads(state_path.read_text())
            self.assertEqual(state["status"], "succeeded")
            self.assertEqual(state["network"], "none")
            self.assertTrue((root / "asdi" / "evidence" / result["evidence"]["manifest_id"]).is_dir())

    def test_verifier_only_missed_control_is_red(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product, commit = self.make_product(root)
            runtime = FakeRuntime(root / "workspace", root / "evidence")
            runtime.verify_result = {
                "schema": 2,
                "run_id": "filled-by-verifier",
                "commit": commit,
                "features": [
                    {
                        "id": "feature:notes",
                        "status": "pass",
                        "control": "missed",
                        "evidence": ["verifier-output.txt"],
                        "limits": [],
                    }
                ],
            }
            launcher = REVKLauncher(
                root=root / "asdi",
                product_root=product,
                base_branch="main",
                runtime=runtime,
            )

            def verify_head(
                *,
                run_id: str,
                commit: str,
                evidence_stage: Path,
                verifier_result,
                **kwargs,
            ):
                runtime.verify_result["run_id"] = run_id
                runtime.verify_result["commit"] = commit
                evidence_stage.mkdir(parents=True, exist_ok=True)
                (evidence_stage / "verifier-output.txt").write_text("defect observed\n")
                (evidence_stage / "result.json").write_text(
                    json.dumps(
                        {
                            "schema": 2,
                            "run_id": run_id,
                            "commit": commit,
                            "features": [
                                {
                                    "id": "feature:notes",
                                    "status": "pass",
                                    "control": "missed",
                                    "evidence": ["verifier-output.txt"],
                                    "limits": [],
                                }
                            ],
                        }
                    )
                )
                verifier_result.update(
                    json.loads((evidence_stage / "result.json").read_text())
                )
                return [
                    {"id": "static:compile", "status": "pass"},
                    {"id": "verify:base-harness", "status": "pass"},
                ]

            with patch.object(launcher, "_verify_head", verify_head):
                result = launcher.verify_revision(commit)

            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["evidence"]["result"]["features"][0]["status"] == "pass")
            self.assertFalse(runtime.started)
            self.assertTrue(runtime.removed_volume)

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
