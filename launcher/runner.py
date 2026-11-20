#!/usr/bin/env python3
"""REV K Pass 1 launcher: isolated local run, verifier, and evidence."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from events.config import load_operational_defaults

from .contract import load_contract
from .evidence import EvidenceStore
from .agent_adapters import ADAPTERS, adapter_script
from .static_gates import run_checks as run_container_checks
from .static_gates import kill_and_remove
from .state import atomic_json


@dataclass
class RunResult:
    run_id: str
    status: str
    agent_exit_code: int | None
    checks: list[dict[str, Any]]
    evidence: dict[str, Any]
    runtime: dict[str, Any]


class DockerRuntime:
    """Thin Docker CLI driver.  This is the only component that names it."""

    def __init__(self, docker_path: str | Path | None = None) -> None:
        self.docker = str(docker_path or shutil.which("docker") or "docker")

    def _run(self, arguments: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.docker, *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def create_network(self, name: str) -> None:
        result = self._run(["network", "create", "--internal", name])
        if result.returncode != 0 and "already exists" not in result.stderr:
            raise RuntimeError(f"cannot create run network: {result.stderr}")

    def ensure_bridge_network(self, name: str) -> None:
        result = self._run(["network", "inspect", name], timeout=10)
        if result.returncode == 0:
            return
        result = self._run(["network", "create", name], timeout=10)
        if result.returncode != 0 and "already exists" not in result.stderr:
            raise RuntimeError(f"cannot create egress network: {result.stderr}")

    def create_volume(self, name: str) -> None:
        result = self._run(["volume", "create", name])
        if result.returncode != 0 and "already in use" not in result.stderr and "already exists" not in result.stderr:
            raise RuntimeError(f"cannot create evidence volume: {result.stderr}")

    def populate_volume(self, volume: str, source: Path, *, destination: str = "/workspace") -> None:
        helper = f"asdi-volume-populate-{uuid.uuid4().hex[:12]}"
        started = self._run(
            [
                "run",
                "-d",
                "--rm",
                "--name",
                helper,
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "CHOWN",
                "-v",
                f"{volume}:{destination}",
                "ubuntu:noble",
                "sleep",
                "60",
            ],
            timeout=30,
        )
        if started.returncode != 0:
            raise RuntimeError(f"cannot start volume population helper: {started.stderr}")
        try:
            copied = self._run(["cp", f"{source}/.", f"{helper}:{destination}"], timeout=120)
            if copied.returncode != 0:
                raise RuntimeError(f"cannot populate run volume: {copied.stderr}")
        finally:
            self._run(["rm", "-f", helper], timeout=10)

    def chown_volume(self, volume: str, destination: str, ownership: str) -> None:
        helper = f"asdi-volume-chown-{uuid.uuid4().hex[:12]}"
        started = self._run(
            [
                "run",
                "-d",
                "--rm",
                "--name",
                helper,
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "CHOWN",
                "-v",
                f"{volume}:{destination}",
                "ubuntu:noble",
                "sleep",
                "60",
            ],
            timeout=30,
        )
        if started.returncode != 0:
            raise RuntimeError(f"cannot start volume ownership helper: {started.stderr}")
        try:
            changed = self._run(
                ["exec", helper, "chown", "-R", ownership, destination],
                timeout=30,
            )
            if changed.returncode != 0:
                raise RuntimeError(f"cannot set volume ownership: {changed.stderr}")
        finally:
            self._run(["rm", "-f", helper], timeout=10)

    def start(
        self,
        *,
        name: str,
        image: str,
        network: str,
        command: list[str],
        binds: list[str],
        environment: dict[str, str] | None = None,
        user: str | None = None,
    ) -> subprocess.Popen[str]:
        arguments = [
            "run",
            "--name",
            name,
            "--network",
            network,
            "--init",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=128m",
            "--memory",
            "1g",
            "--cpus",
            "1",
            "--pids-limit",
            "128",
        ]
        for bind in binds:
            arguments.extend(("--mount", bind))
        for key, value in (environment or {}).items():
            arguments.extend(("--env", f"{key}={value}"))
        if user:
            arguments.extend(("--user", user))
        arguments.extend((image, *command))
        Path("/tmp/asdi-docker-run-command.json").write_text(json.dumps(arguments, indent=2))
        return subprocess.Popen(
            [self.docker, *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def kill(self, name: str) -> None:
        self._run(["kill", name], timeout=10)

    def pause(self, name: str) -> None:
        result = self._run(["pause", name], timeout=10)
        if result.returncode != 0:
            raise RuntimeError(f"cannot pause run container: {result.stderr}")

    def unpause(self, name: str) -> None:
        result = self._run(["unpause", name], timeout=10)
        if result.returncode != 0:
            raise RuntimeError(f"cannot resume run container: {result.stderr}")

    def remove_container(self, name: str) -> None:
        self._run(["rm", "-f", name], timeout=10)

    def remove_network(self, name: str) -> None:
        self._run(["network", "rm", name], timeout=10)

    def remove_volume(self, name: str) -> None:
        self._run(["volume", "rm", name], timeout=10)

    def teardown_run_resources(
        self,
        *,
        network: str,
        evidence_volume: str,
        workspace_volume: str,
        base_volume: str,
    ) -> None:
        self.remove_network(network)
        self.remove_volume(evidence_volume)
        self.remove_volume(workspace_volume)
        self.remove_volume(base_volume)

    def teardown_verifier_resources(
        self,
        *,
        workspace_volume: str,
        base_volume: str,
    ) -> None:
        """Remove only verifier-only resources; verifier containers have no network."""

        self.remove_volume(workspace_volume)
        self.remove_volume(base_volume)

    def stop_proxy(self, name: str) -> None:
        self.kill(name)
        self.remove_container(name)

    def copy_volume(self, volume: str, destination: Path, image: str) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                "run",
                "--rm",
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "-v",
                f"{volume}:/evidence:ro",
                "-v",
                f"{destination}:/stage",
                image,
                "/bin/sh",
                "-lc",
                "cp -a /evidence/. /stage/",
            ],
            timeout=60,
        )

    def inspect_image(self, image: str) -> str:
        result = self._run(["image", "inspect", "--format", "{{.Id}}", image], timeout=10)
        if result.returncode != 0:
            raise RuntimeError(f"cannot inspect run image: {result.stderr}")
        return result.stdout.strip()

    def start_proxy(
        self,
        *,
        name: str,
        egress_network: str,
        script: Path,
        image: str,
        environment: dict[str, str],
    ) -> None:
        arguments = [
            "run",
            "-d",
            "--name",
            name,
            "--network",
            egress_network,
            "--init",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--user",
            "1001:1001",
            "--entrypoint",
            "/usr/bin/python3",
            "--mount",
            f"type=bind,source={script},destination=/opt/asdi/egress_proxy.py,ro",
        ]
        for key, value in environment.items():
            arguments.extend(("--env", f"{key}={value}"))
        arguments.extend((image, "/opt/asdi/egress_proxy.py"))
        started = self._run(arguments, timeout=30)
        if started.returncode != 0:
            raise RuntimeError(f"cannot start egress proxy: {started.stderr}")

    def connect_network(self, container: str, network: str) -> None:
        result = self._run(["network", "connect", network, container], timeout=10)
        if result.returncode != 0 and "already exists" not in result.stderr:
            raise RuntimeError(
                f"cannot attach egress proxy to run network: {result.stderr}"
            )


class REVKLauncher:
    """Pass 1 launcher using one isolated Docker run and one verifier."""

    def __init__(
        self,
        *,
        root: str | Path,
        product_root: str | Path,
        base_branch: str = "main",
        agent_image: str = "safeclaw:cc-2.1.283",
        agent_adapter: str = "fixture",
        verifier_image: str | None = None,
        proxy_image: str = "safeclaw-us-egress:cc-2.1.283",
        egress_network: str = "asdi-egress",
        egress_script: str | Path | None = None,
        model_endpoint: str = "http://host.docker.internal:4000/v1",
        model_key_env: str = "LITELLM_MASTER_KEY",
        runtime: DockerRuntime | None = None,
        agent_script: str | Path | None = None,
        agent_default_cost_usd: float = 0.0,
    ) -> None:
        self.root = Path(root).resolve()
        self.runs_root = self.root / "runs"
        self.product_root = Path(product_root).resolve()
        self.base_branch = base_branch
        self.agent_image = agent_image
        if agent_adapter not in ADAPTERS:
            raise ValueError(f"unknown agent adapter: {agent_adapter}")
        self.agent_adapter = agent_adapter
        self.verifier_image = verifier_image or agent_image
        self.proxy_image = proxy_image
        self.egress_network = egress_network
        self.egress_script = Path(
            egress_script or Path(__file__).resolve().parent / "egress_proxy.py"
        ).resolve()
        parsed_model = urllib.parse.urlsplit(model_endpoint)
        self.model_base_url = model_endpoint
        self.model_host = parsed_model.hostname or "host.docker.internal"
        self.model_port = parsed_model.port or (
            443 if parsed_model.scheme == "https" else 80
        )
        self.model_key_env = model_key_env
        self.runtime = runtime or DockerRuntime()
        self.agent_script = Path(
            agent_script
            or adapter_script(Path(__file__).resolve().parent / "agents", agent_adapter)
        ).resolve()
        self.agent_default_cost_usd = agent_default_cost_usd
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def run(self, contract_path: str | Path) -> RunResult:
        contract = load_contract(contract_path)
        run_id = f"r-{uuid.uuid4()}"
        short = run_id.removeprefix("r-").replace("-", "")[:16]
        network = f"asdi-run-{short}"
        volume = f"asdi-evidence-{short}"
        workspace_volume = f"asdi-workspace-{short}"
        base_volume = f"asdi-base-{short}"
        container = f"asdi-agent-{short}"
        proxy = f"asdi-egress-{short}"
        run_root = self.runs_root / run_id
        workspace = run_root / "workspace"
        evidence_stage = run_root / "evidence"
        evidence_stage.mkdir(parents=True, exist_ok=True)
        pid = os.getpid()
        self._save_state(
            run_root,
            {
                "run_id": run_id,
                "status": "running",
                "contract_path": str(Path(contract_path).resolve()),
                "container": container,
                "network": network,
                "pid": pid,
                "evidence_volume": volume,
                "workspace_volume": workspace_volume,
                "base_volume": base_volume,
                "egress_container": proxy,
                "started_at": time.time(),
            },
        )

        spend_limit = contract["guardrails"].get("spend_usd")
        if spend_limit is not None and self.agent_default_cost_usd > float(spend_limit):
            self._record_failure(
                run_root,
                RuntimeError("spend guardrail exceeded before launch"),
            )
            raise RuntimeError("spend guardrail exceeded before launch")

        try:
            self._fresh_export(workspace)
            base_export = run_root / "base"
            self._fresh_export(base_export)
            self.runtime.create_network(network)
            self.runtime.create_volume(volume)
            self.runtime.create_volume(workspace_volume)
            self.runtime.create_volume(base_volume)
            self.runtime.ensure_bridge_network(self.egress_network)
            self.runtime.populate_volume(workspace_volume, workspace)
            self.runtime.populate_volume(base_volume, base_export, destination="/opt/base")
            self.runtime.chown_volume(workspace_volume, "/workspace", "1001:1001")
            self.runtime.chown_volume(volume, "/evidence", "1001:1001")
            model_key = os.environ.get(self.model_key_env)
            proxy_environment = {
                "ASDI_MODEL_HOST": self.model_host,
                "ASDI_MODEL_PORT": str(self.model_port),
                "ASDI_EGRESS_ALLOWLIST": ",".join(
                    [
                        "github.com:443",
                        "api.github.com:443",
                        "objects.githubusercontent.com:443",
                        "codeload.github.com:443",
                        "pypi.org:443",
                        "files.pythonhosted.org:443",
                        "registry.npmjs.org:443",
                        "registry.npmmirror.com:443",
                    ]
                ),
            }
            if model_key:
                proxy_environment["ASDI_MODEL_API_KEY"] = model_key
            self.runtime.start_proxy(
                name=proxy,
                egress_network=self.egress_network,
                script=self.egress_script,
                image=self.proxy_image,
                environment=proxy_environment,
            )
            self.runtime.connect_network(proxy, network)
        except Exception as error:
            self.runtime.stop_proxy(proxy)
            self.runtime.teardown_run_resources(
                network=network,
                evidence_volume=volume,
                workspace_volume=workspace_volume,
                base_volume=base_volume,
            )
            self._record_failure(run_root, error)
            raise

        environment = {
            "ASDI_RUN_ID": run_id,
            "ASDI_EVIDENCE_DIR": "/evidence",
            "ASDI_MODEL_BASE_URL": self.model_base_url,
            "ASDI_MODEL_PROXY_URL": f"http://{proxy}:8081",
            "ASDI_AGENT_MODEL": contract.get("model") or "qwen3.6-35b-dspark-local",
            "ASDI_OBJECTIVE": contract["objective"],
            "ASDI_WHY": contract["why"],
            "ASDI_CONSTRAINTS": "; ".join(contract.get("constraints", [])),
            "ASDI_OUT_OF_SCOPE": "; ".join(contract.get("out_of_scope", [])),
            "ASDI_DONE_CHECK": " ".join(
                map(shlex.quote, contract["done_check"]["command"])
            ),
            "HOME": "/tmp",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HTTP_PROXY": f"http://{proxy}:8081",
            "HTTPS_PROXY": f"http://{proxy}:8081",
            "NO_PROXY": f"localhost,127.0.0.1,{proxy}",
        }
        command = [
            "/usr/bin/python3",
            f"/opt/asdi/{ADAPTERS[self.agent_adapter].script_name}",
            "--workspace",
            "/workspace",
            "--run-id",
            run_id,
            "--commit",
            self._head(),
        ]
        started = time.time()
        turns = 0
        tokens = 0
        spend_used = 0.0
        agent_exit: int | None = None
        output_lines: queue.Queue[str] = queue.Queue()
        reader_finished = threading.Event()

        def drain_process_output() -> None:
            try:
                if process.stdout is None:
                    return
                for line in process.stdout:
                    output_lines.put(line)
            finally:
                reader_finished.set()

        def observe_runtime_events() -> None:
            nonlocal turns, tokens, spend_used
            while True:
                try:
                    raw = output_lines.get_nowait()
                except queue.Empty:
                    return
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "turn":
                    turns += 1
                if event.get("event") == "usage":
                    tokens += int(event.get("tokens", 0))
                    spend_used += float(event.get("usd", 0))

        def enforce_runtime_guardrails() -> None:
            token_limit = contract["guardrails"].get("tokens")
            if token_limit is not None and tokens > int(token_limit):
                self.runtime.kill(container)
                raise RuntimeError("token guardrail exceeded")
            spend_limit = contract["guardrails"].get("spend_usd")
            if spend_limit is not None and spend_used > float(spend_limit):
                self.runtime.kill(container)
                raise RuntimeError("spend guardrail exceeded")
            if turns > int(contract["guardrails"]["turns"]):
                self.runtime.kill(container)
                raise RuntimeError("turn guardrail exceeded")

        try:
            process = self.runtime.start(
                name=container,
                image=self.agent_image,
                network=network,
                command=command,
                binds=[
                    f"type=volume,source={workspace_volume},destination=/workspace",
                    f"type=bind,source={self.agent_script},destination=/opt/asdi/{ADAPTERS[self.agent_adapter].script_name},ro",
                    f"type=volume,source={volume},destination=/evidence",
                ],
                user="1001:1001",
                environment=environment,
            )
            limit = float(contract["guardrails"]["minutes"]) * 60
            threading.Thread(target=drain_process_output, daemon=True).start()
            while process.poll() is None:
                if time.time() - started > limit:
                    self.runtime.kill(container)
                    raise RuntimeError("wall-clock guardrail exceeded")
                observe_runtime_events()
                enforce_runtime_guardrails()
                time.sleep(0.1)
            while not reader_finished.is_set() or not output_lines.empty():
                observe_runtime_events()
                enforce_runtime_guardrails()
            agent_exit = process.returncode
            stdout, stderr = process.communicate(timeout=5)
            (run_root / "agent.stdout.log").write_text(stdout or "")
            (run_root / "agent.stderr.log").write_text(stderr or "")
            if not os.environ.get("ASDI_KEEP_CONTAINER"):
                self.runtime.remove_container(container)
        except Exception as error:
            self.runtime.kill(container)
            self.runtime.stop_proxy(proxy)
            self.runtime.teardown_run_resources(
                network=network,
                evidence_volume=volume,
                workspace_volume=workspace_volume,
                base_volume=base_volume,
            )
            self._record_failure(run_root, error)
            raise

        self.runtime.stop_proxy(proxy)

        spend_limit = contract["guardrails"].get("spend_usd")
        spend_used += self.agent_default_cost_usd
        if spend_limit is not None and spend_used > float(spend_limit):
            self.runtime.kill(container)
            self.runtime.stop_proxy(proxy)
            self.runtime.teardown_run_resources(
                network=network,
                evidence_volume=volume,
                workspace_volume=workspace_volume,
                base_volume=base_volume,
            )
            error = RuntimeError("spend guardrail exceeded")
            self._record_failure(run_root, error)
            raise error

        try:
            self.runtime.copy_volume(volume, evidence_stage, self.verifier_image)

            verifier_result: dict[str, Any] = {}
            checks = self._verify_head(
                run_id=run_id,
                workspace=workspace,
                workspace_volume=workspace_volume,
                base_volume=base_volume,
                evidence_stage=evidence_stage,
                verifier_result=verifier_result,
                commit=self._head(),
            )
            passed = agent_exit == 0 and all(
                check["status"] == "pass" for check in checks if check.get("blocking", True)
            )
            status = "succeeded" if passed else "failed"
            result_path = evidence_stage / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "schema": 2,
                        "run_id": run_id,
                        "commit": self._head(),
                        "features": verifier_result.get(
                            "features",
                            [
                                {
                                    "id": "lifecycle-smoke",
                                    "status": "pass" if passed else "fail",
                                    "control": "caught",
                                    "evidence": [],
                                    "limits": ["Pass 1 fixture checks only"],
                                }
                            ],
                        ),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            gates_path = base_export / ".asdi" / "static-gates.yaml"
            profile_path = base_export / ".asdi" / "product.yaml"
            evidence_metadata = {
                "source": "run",
                "producer": {
                    "kind": "verifier",
                    "image_digest": self.runtime.inspect_image(self.verifier_image),
                },
                "environment": {
                    "run_image_digest": self.runtime.inspect_image(self.agent_image),
                    "tool_versions": {"python": "container-image"},
                },
                "inputs": {
                    "harness_commit": self._revision(self.base_branch),
                    "static_gates": self._file_digest(gates_path),
                    "product_profile": self._file_digest(profile_path),
                },
            }
            evidence = EvidenceStore(self.root / "evidence").put(
                evidence_stage,
                json.loads(result_path.read_text()),
                metadata=evidence_metadata,
            )
            runtime_evidence = {
                "network": network,
                "container": container,
                "evidence_volume": volume,
                "workspace_volume": workspace_volume,
                "egress_container": proxy,
                "egress_mode": "allowlist_proxy",
                "egress_allowlist": proxy_environment["ASDI_EGRESS_ALLOWLIST"].split(","),
                "socket_mounted": False,
                "secrets_mounted": False,
                "usage": {"turns": turns, "tokens": tokens, "spend_usd": spend_used},
            }
            self._save_state(
                run_root,
                {
                    "run_id": run_id,
                    "status": status,
                    "pid": pid,
                    "agent_exit_code": agent_exit,
                    "checks": checks,
                    "evidence": evidence,
                    "runtime": runtime_evidence,
                    "started_at": self._saved_started_at(run_root),
                    "finished_at": time.time(),
                },
            )
            self.runtime.teardown_run_resources(
                network=network,
                evidence_volume=volume,
                workspace_volume=workspace_volume,
                base_volume=base_volume,
            )
            return RunResult(
                run_id=run_id,
                status=status,
                agent_exit_code=agent_exit,
                checks=checks,
                evidence=evidence,
                runtime=runtime_evidence,
            )
        except Exception as error:
            self.runtime.teardown_run_resources(
                network=network,
                evidence_volume=volume,
                workspace_volume=workspace_volume,
                base_volume=base_volume,
            )
            self._record_failure(run_root, error)
            raise

    def verify_revision(
        self,
        revision: str,
        *,
        source: str = "pr-head",
    ) -> dict[str, Any]:
        """Verify one exact revision without launching an agent.

        This is the Phase 4 verifier entry point.  It starts no agent, no proxy,
        and no run network.  Static checks and the base harness still execute in
        the verifier container with ``--network none``.
        """

        if source not in {"pr-head", "main"}:
            raise ValueError("verification source must be pr-head or main")
        commit = self._revision(revision)
        if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
            raise ValueError("verification revision must resolve to a full Git SHA")
        run_id = f"r-v{uuid.uuid4().hex}"
        short = run_id[2:18]
        run_root = self.runs_root / run_id
        workspace = run_root / "workspace"
        base = run_root / "base"
        evidence_stage = run_root / "evidence"
        evidence_stage.mkdir(parents=True, exist_ok=True)
        workspace_volume = f"asdi-verify-workspace-{short}"
        base_volume = f"asdi-verify-base-{short}"
        started = time.time()
        self._save_state(
            run_root,
            {
                "run_id": run_id,
                "mode": "verifier_only",
                "status": "verifying",
                "revision": revision,
                "commit": commit,
                "source": source,
                "workspace_volume": workspace_volume,
                "base_volume": base_volume,
                "network": "none",
                "started_at": started,
            },
        )
        try:
            self._fresh_export(workspace, revision=revision)
            self._fresh_export(base, revision=self.base_branch)
            self.runtime.create_volume(workspace_volume)
            self.runtime.create_volume(base_volume)
            self.runtime.populate_volume(workspace_volume, workspace)
            self.runtime.populate_volume(base_volume, base, destination="/opt/base")
            self.runtime.chown_volume(workspace_volume, "/workspace", "1001:1001")
            verifier_result: dict[str, Any] = {}
            checks = self._verify_head(
                run_id=run_id,
                workspace=workspace,
                workspace_volume=workspace_volume,
                base_volume=base_volume,
                evidence_stage=evidence_stage,
                verifier_result=verifier_result,
                commit=commit,
            )
            features = verifier_result.get("features")
            valid_features = isinstance(features, list) and bool(features) and all(
                isinstance(feature, dict)
                and feature.get("status") == "pass"
                and feature.get("control") == "caught"
                and isinstance(feature.get("limits"), list)
                for feature in features
            )
            if valid_features:
                result_features = features
            else:
                result_features = [
                    {
                        "id": "verification-result",
                        "status": "fail",
                        "control": "caught",
                        "evidence": [],
                        "limits": ["Verifier did not produce a valid caught-control result"],
                    }
                ]
            result_path = evidence_stage / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "schema": 2,
                        "run_id": run_id,
                        "commit": commit,
                        "features": result_features,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            gates_path = base / ".asdi" / "static-gates.yaml"
            profile_path = base / ".asdi" / "product.yaml"
            evidence = EvidenceStore(self.root / "evidence").put(
                evidence_stage,
                json.loads(result_path.read_text()),
                metadata={
                    "source": source,
                    "producer": {
                        "kind": "verifier",
                        "image_digest": self.runtime.inspect_image(self.verifier_image),
                    },
                    "environment": {
                        "run_image_digest": self.runtime.inspect_image(self.verifier_image),
                        "tool_versions": {"python": "container-image"},
                    },
                    "inputs": {
                        "harness_commit": self._revision(self.base_branch),
                        "static_gates": self._file_digest(gates_path),
                        "product_profile": self._file_digest(profile_path),
                    },
                },
            )
            status = "succeeded" if valid_features else "failed"
            runtime_evidence = {
                "mode": "verifier_only",
                "network": "none",
                "socket_mounted": False,
                "secrets_mounted": False,
                "agent_started": False,
                "workspace_volume": workspace_volume,
                "base_volume": base_volume,
            }
            self._save_state(
                run_root,
                {
                    "run_id": run_id,
                    "mode": "verifier_only",
                    "status": status,
                    "revision": revision,
                    "commit": commit,
                    "source": source,
                    "checks": checks,
                    "evidence": evidence,
                    "runtime": runtime_evidence,
                    "network": "none",
                    "started_at": self._saved_started_at(run_root),
                    "finished_at": time.time(),
                },
            )
            self.runtime.teardown_verifier_resources(
                workspace_volume=workspace_volume,
                base_volume=base_volume,
            )
            return {
                "schema_version": "asdi.verifier-only-result/v1",
                "run_id": run_id,
                "status": status,
                "revision": revision,
                "commit": commit,
                "source": source,
                "checks": checks,
                "evidence": evidence,
                "runtime": runtime_evidence,
            }
        except Exception as error:
            self.runtime.teardown_verifier_resources(
                workspace_volume=workspace_volume,
                base_volume=base_volume,
            )
            self._record_failure(run_root, error)
            raise

    def _save_state(self, run_root: Path, state: dict[str, Any]) -> None:
        atomic_json(run_root / "launcher-state.json", state)

    def _saved_started_at(self, run_root: Path) -> float:
        try:
            return float(
                json.loads((run_root / "launcher-state.json").read_text())["started_at"]
            )
        except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
            return time.time()

    def _record_failure(self, run_root: Path, error: Exception) -> None:
        try:
            state = json.loads((run_root / "launcher-state.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            state = {"run_id": run_root.name, "status": "running"}
        state.update(
            {
                "status": "failed",
                "failure": {
                    "type": type(error).__name__,
                    "message": str(error),
                    "at": time.time(),
                },
                "finished_at": time.time(),
            }
        )
        atomic_json(run_root / "launcher-state.json", state)

    def _verify_head(
        self,
        *,
        run_id: str,
        workspace: Path,
        workspace_volume: str,
        base_volume: str,
        evidence_stage: Path,
        verifier_result: dict[str, Any],
        commit: str,
    ) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "base"
            base.mkdir()
            self._export_tree(self.base_branch, base)
            gates_path = base / ".asdi" / "static-gates.yaml"
            if not gates_path.is_file():
                raise RuntimeError("base branch is missing static-gates manifest")
            manifest = _minimal_yaml(gates_path.read_text())
            workspace_inspect = Path(temporary) / "workspace-inspect"
            workspace_inspect.mkdir()
            checks = run_container_checks(
                docker=self.runtime.docker,
                image=self.verifier_image,
                manifest=manifest,
                run_id=run_id,
                commit=commit,
                mounts=[
                    f"type=volume,source={workspace_volume},destination=/workspace",
                    f"type=volume,source={base_volume},destination=/opt/base,readonly",
                ],
            )
            verify_check = self._run_base_verify(
                run_id=run_id,
                base=base,
                workspace_volume=workspace_volume,
                base_volume=base_volume,
                commit=commit,
            )
            checks.append(verify_check)
            (workspace_inspect / ".asdi-evidence" / "static-gates.json").parent.mkdir(
                parents=True, exist_ok=True
            )
            (workspace_inspect / ".asdi-evidence" / "static-gates.json").write_text(
                json.dumps({"run_id": run_id, "checks": checks}, indent=2, sort_keys=True) + "\n"
            )
            for runtime_log in ("claude.stdout.log", "claude.stderr.log"):
                runtime_log_path = workspace / runtime_log
                if runtime_log_path.is_file():
                    shutil.copy2(
                        runtime_log_path,
                        workspace_inspect / ".asdi-evidence" / runtime_log,
                    )
            self.runtime.copy_volume(
                workspace_volume,
                workspace_inspect,
                self.verifier_image,
            )
            self._collect_verify_result(
                workspace=workspace_inspect,
                run_id=run_id,
                commit=commit,
                verify_check=verify_check,
                verifier_result=verifier_result,
            )
            workspace_evidence = workspace_inspect / ".asdi-evidence"
            if workspace_evidence.is_dir():
                for evidence_file in sorted(workspace_evidence.glob("*")):
                    if evidence_file.is_file() and evidence_file.name != "result.json":
                        shutil.copy2(evidence_file, evidence_stage / evidence_file.name)
            return checks

    @staticmethod
    def _collect_verify_result(
        *,
        workspace: Path,
        run_id: str,
        commit: str,
        verify_check: dict[str, Any],
        verifier_result: dict[str, Any],
    ) -> None:
        result_path = workspace / ".asdi-evidence" / "result.json"
        if verify_check.get("status") != "pass":
            return
        try:
            observed = json.loads(result_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError) as error:
            verify_check["status"] = "error"
            verify_check["stderr"] = (
                f"base verifier did not produce valid result.json: {error}"
            )
            return
        failures: list[str] = []
        if observed.get("schema") != 2:
            failures.append("schema must be 2")
        if observed.get("run_id") != run_id:
            failures.append("run_id mismatch")
        if observed.get("commit") != commit:
            failures.append("commit mismatch")
        features = observed.get("features")
        if not isinstance(features, list) or not features:
            failures.append("features must be a non-empty array")
        for feature in features or []:
            if feature.get("status") != "pass":
                failures.append(f"feature {feature.get('id')} is not pass")
            if feature.get("control") != "caught":
                failures.append(f"feature {feature.get('id')} control was not caught")
            if not feature.get("limits"):
                failures.append(f"feature {feature.get('id')} has no limits")
        if failures:
            verify_check["status"] = "fail"
            verify_check["stderr"] = "; ".join(failures)
            return
        verifier_result.update(observed)

    def _run_base_verify(
        self,
        *,
        run_id: str,
        base: Path,
        workspace_volume: str,
        base_volume: str,
        commit: str,
    ) -> dict[str, Any]:
        """Run the base-branch verify entrypoint after static gates."""

        verify_path = base / "verify" / "bin" / "verify"
        started = time.time()
        short = run_id.removeprefix("r-v").removeprefix("r-").replace("-", "")[:16]
        container = f"asdi-verify-{short}"
        if not verify_path.is_file() or not os.access(verify_path, os.X_OK):
            return {
                "id": "verify:base-harness",
                "status": "blocked",
                "exit_code": None,
                "duration_seconds": round(time.time() - started, 3),
                "stdout": "",
                "stderr": "base branch has no executable verify/bin/verify",
            }
        command = [
            self.runtime.docker,
            "run",
            "--rm",
            "--name",
            container,
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--mount",
            f"type=volume,source={workspace_volume},destination=/workspace",
            "--mount",
            f"type=volume,source={base_volume},destination=/opt/base,readonly",
            "--workdir",
            "/workspace",
            "--env",
            f"ASDI_RUN_ID={run_id}",
            "--env",
            f"ASDI_COMMIT={commit}",
            "--env",
            "ASDI_HEAD=/workspace",
            "--env",
            "ASDI_BASE=/opt/base",
            "--env",
            "ASDI_EVIDENCE_DIR=/workspace/.asdi-evidence",
            self.verifier_image,
            "/opt/base/verify/bin/verify",
        ]
        timed_out = False
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=load_operational_defaults().verifier_timeout_seconds,
                check=False,
            )
            status = "pass" if completed.returncode == 0 else "fail"
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            timed_out = True
            status = "error"
            exit_code = None
            stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else str(error.stdout or "")
            stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else str(error.stderr or "")
            cleanup = kill_and_remove(self.runtime.docker, container)
        except OSError as error:
            status = "error"
            exit_code = None
            stdout = ""
            stderr = str(error)
        return {
            "id": "verify:base-harness",
            "status": status,
            "exit_code": exit_code,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
            "container": container,
            "timeout_killed": timed_out,
            "timeout_cleanup": cleanup if timed_out else [],
        }

    def _fresh_export(self, destination: Path, *, revision: str | None = None) -> None:
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        self._export_tree(revision or self.base_branch, destination)

    def _head(self) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.product_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _revision(self, revision: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.product_root), "rev-parse", revision],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    @staticmethod
    def _file_digest(path: Path) -> str:
        if not path.is_file():
            return hashlib.sha256(b"").hexdigest()
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _export_tree(self, revision: str, output: Path) -> None:
        archive = output.parent / f".{output.name}-{uuid.uuid4().hex}.tar"
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.product_root),
                "archive",
                "--format=tar",
                revision,
                "-o",
                str(archive),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git failed: {result.stderr}")
        extract = subprocess.run(
            ["tar", "-x", "-C", str(output), "-f", str(archive)],
            capture_output=True,
            text=True,
            check=False,
        )
        archive.unlink(missing_ok=True)
        if extract.returncode != 0:
            raise RuntimeError(f"could not extract git archive: {extract.stderr}")




def _minimal_yaml(value: str) -> dict[str, Any]:
    """Parse the deliberately narrow Phase 1 static-gate manifest."""

    checks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    command: list[str] | None = None
    policy = {"new_violations": "reject", "legacy_findings": "track_without_expanding"}
    for raw_line in value.splitlines():
        line = raw_line.rstrip()
        if line.startswith("checks:"):
            continue
        if line.startswith("  - id:"):
            if current:
                checks.append(current)
            current = {"id": line.split(":", 1)[1].strip(), "blocking": True, "timeout_seconds": 300}
            command = None
        elif current is not None:
            if line.strip().startswith("- "):
                if command is None:
                    command = []
                    current["command"] = command
                command.append(line.strip()[2:].strip("'\""))
            elif line.strip().startswith("blocking:"):
                current["blocking"] = line.split(":", 1)[1].strip() == "true"
            elif line.strip().startswith("command: ["):
                current["command"] = json.loads(line.split(":", 1)[1].strip())
            elif line.strip().startswith("timeout_seconds:"):
                current["timeout_seconds"] = int(line.split(":", 1)[1].strip())
    if current:
        checks.append(current)
    return {"version": 1, "checks": checks, "policy": policy}
