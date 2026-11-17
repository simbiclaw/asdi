#!/usr/bin/env python3
"""REV K Pass 1 launcher: isolated local run, verifier, and evidence."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract import load_contract
from .evidence import EvidenceStore
from .static_gates import run_checks as run_container_checks
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

    def remove_container(self, name: str) -> None:
        self._run(["rm", "-f", name], timeout=10)

    def remove_network(self, name: str) -> None:
        self._run(["network", "rm", name], timeout=10)

    def remove_volume(self, name: str) -> None:
        self._run(["volume", "rm", name], timeout=10)

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


class REVKLauncher:
    """Pass 1 launcher using one isolated Docker run and one verifier."""

    def __init__(
        self,
        *,
        root: str | Path,
        product_root: str | Path,
        base_branch: str = "main",
        agent_image: str = "safeclaw:cc-2.1.283",
        verifier_image: str | None = None,
        runtime: DockerRuntime | None = None,
        agent_script: str | Path | None = None,
        agent_default_cost_usd: float = 0.0,
    ) -> None:
        self.root = Path(root).resolve()
        self.runs_root = self.root / "runs"
        self.product_root = Path(product_root).resolve()
        self.base_branch = base_branch
        self.agent_image = agent_image
        self.verifier_image = verifier_image or agent_image
        self.runtime = runtime or DockerRuntime()
        self.agent_script = Path(
            agent_script or Path(__file__).resolve().parent / "agents" / "fixture_agent.py"
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
        run_root = self.runs_root / run_id
        workspace = run_root / "workspace"
        evidence_stage = run_root / "evidence"
        evidence_stage.mkdir(parents=True, exist_ok=True)
        self._save_state(
            run_root,
            {
                "run_id": run_id,
                "status": "running",
                "contract_path": str(Path(contract_path).resolve()),
                "container": container,
                "network": network,
                "started_at": time.time(),
            },
        )

        self._fresh_export(workspace)
        base_export = run_root / "base"
        self._fresh_export(base_export)
        self.runtime.create_network(network)
        self.runtime.create_volume(volume)
        self.runtime.create_volume(workspace_volume)
        self.runtime.create_volume(base_volume)
        self.runtime.populate_volume(workspace_volume, workspace)
        self.runtime.populate_volume(base_volume, base_export, destination="/opt/base")
        self.runtime.chown_volume(workspace_volume, "/workspace", "1001:1001")
        self.runtime.chown_volume(volume, "/evidence", "1001:1001")

        environment = {
            "ASDI_RUN_ID": run_id,
            "ASDI_EVIDENCE_DIR": "/evidence",
            "HOME": "/tmp",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }
        spend_limit = contract["guardrails"].get("spend_usd")
        if spend_limit is not None and self.agent_default_cost_usd > float(spend_limit):
            raise RuntimeError("spend guardrail exceeded before launch")
        command = [
            "/usr/bin/python3",
            "/opt/asdi/fixture_agent.py",
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
                    f"type=bind,source={self.agent_script},destination=/opt/asdi/fixture_agent.py,ro",
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
        except Exception:
            self.runtime.kill(container)
            raise

        spend_limit = contract["guardrails"].get("spend_usd")
        spend_used += self.agent_default_cost_usd
        if spend_limit is not None and spend_used > float(spend_limit):
            self.runtime.kill(container)
            raise RuntimeError("spend guardrail exceeded")

        self.runtime.copy_volume(volume, evidence_stage, self.verifier_image)

        checks = self._verify_head(
            run_id=run_id,
            workspace=workspace,
            base_volume=base_volume,
        )
        passed = agent_exit == 0 and all(check["status"] == "pass" for check in checks)
        status = "succeeded" if passed else "failed"
        result_path = evidence_stage / "result.json"
        result_path.write_text(
            json.dumps(
                {
                    "schema": 2,
                    "run_id": run_id,
                    "commit": self._head(),
                    "features": [
                        {
                            "id": "lifecycle-smoke",
                            "status": "pass" if passed else "fail",
                            "control": "caught",
                            "evidence": ["agent.stdout.log", "static-gates.json"],
                            "limits": ["Pass 1 fixture checks only"],
                        }
                    ],
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
            "socket_mounted": False,
            "secrets_mounted": False,
            "usage": {"turns": turns, "tokens": tokens, "spend_usd": spend_used},
        }
        self._save_state(
            run_root,
            {
                "run_id": run_id,
                "status": status,
                "agent_exit_code": agent_exit,
                "checks": checks,
                "evidence": evidence,
                "runtime": runtime_evidence,
                "started_at": self._saved_started_at(run_root),
                "finished_at": time.time(),
            },
        )
        self.runtime.remove_network(network)
        self.runtime.remove_volume(volume)
        self.runtime.remove_volume(workspace_volume)
        self.runtime.remove_volume(base_volume)
        return RunResult(
            run_id=run_id,
            status=status,
            agent_exit_code=agent_exit,
            checks=checks,
            evidence=evidence,
            runtime=runtime_evidence,
        )

    def _save_state(self, run_root: Path, state: dict[str, Any]) -> None:
        atomic_json(run_root / "launcher-state.json", state)

    def _saved_started_at(self, run_root: Path) -> float:
        try:
            return float(
                json.loads((run_root / "launcher-state.json").read_text())["started_at"]
            )
        except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
            return time.time()

    def _verify_head(
        self,
        *,
        run_id: str,
        workspace: Path,
        base_volume: str,
    ) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "base"
            base.mkdir()
            self._export_tree(self.base_branch, base)
            gates_path = base / ".asdi" / "static-gates.yaml"
            if not gates_path.is_file():
                raise RuntimeError("base branch is missing static-gates manifest")
            manifest = _minimal_yaml(gates_path.read_text())
            checks = run_container_checks(
                docker=self.runtime.docker,
                image=self.verifier_image,
                manifest=manifest,
                run_id=run_id,
                commit=self._head(),
                mounts=[
                    f"type=volume,source=asdi-workspace-{run_id.removeprefix('r-').replace('-', '')[:16]},destination=/workspace",
                    f"type=volume,source={base_volume},destination=/opt/base:ro",
                ],
            )
            verify_check = self._run_base_verify(
                run_id=run_id,
                base=base,
                base_volume=base_volume,
            )
            checks.append(verify_check)
            (workspace / ".asdi-evidence" / "static-gates.json").parent.mkdir(
                parents=True, exist_ok=True
            )
            (workspace / ".asdi-evidence" / "static-gates.json").write_text(
                json.dumps({"run_id": run_id, "checks": checks}, indent=2, sort_keys=True) + "\n"
            )
            return checks

    def _run_base_verify(
        self,
        *,
        run_id: str,
        base: Path,
        base_volume: str,
    ) -> dict[str, Any]:
        """Run the base-branch verify entrypoint after static gates."""

        verify_path = base / "verify" / "bin" / "verify"
        started = time.time()
        if not verify_path.is_file() or not os.access(verify_path, os.X_OK):
            return {
                "id": "verify:base-harness",
                "status": "blocked",
                "exit_code": None,
                "duration_seconds": round(time.time() - started, 3),
                "stdout": "",
                "stderr": "base branch has no executable verify/bin/verify",
            }
        short = run_id.removeprefix("r-").replace("-", "")[:16]
        command = [
            self.runtime.docker,
            "run",
            "--rm",
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
            f"type=volume,source=asdi-workspace-{short},destination=/workspace",
            "--mount",
            f"type=volume,source={base_volume},destination=/opt/base:ro",
            "--workdir",
            "/workspace",
            "--env",
            f"ASDI_RUN_ID={run_id}",
            "--env",
            "ASDI_HEAD=/workspace",
            "--env",
            "ASDI_BASE=/opt/base",
            "--env",
            "ASDI_EVIDENCE_DIR=/workspace/.asdi-evidence",
            self.verifier_image,
            "/opt/base/verify/bin/verify",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            status = "pass" if completed.returncode == 0 else "fail"
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            status = "error"
            exit_code = None
            stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else str(error.stdout or "")
            stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else str(error.stderr or "")
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
        }

    def _fresh_export(self, destination: Path) -> None:
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        self._export_tree(self.base_branch, destination)

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
