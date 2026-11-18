"""ASDI-012 container-per-run sandbox and host-side egress authority."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .egress import EgressDecision, EgressProxy
from .errors import RuntimeErrorStateError

if TYPE_CHECKING:
    from .runtime import RunStore


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class SandboxSpec:
    """Explicit trusted container configuration.

    ``image`` must already exist locally.  ASDI never pulls an unpinned image
    as a hidden side effect.  ``runtime_executable`` is the absolute path
    inside the container; host executable discovery remains adapter-specific.
    """

    image: str
    runtime_executable: str
    docker_path: str | None = None
    container_user: str | None = None
    egress_host_socket_dir: str = "/tmp"
    workspace_root: str = "/workspace"
    egress_socket: str = "/run/asdi-egress.sock"
    memory: str = "1g"
    cpus: float = 1.0
    pids_limit: int = 128
    stop_timeout: int = 5
    network_profile: str = "contract"


class ContainerSandbox:
    """One immutable-configuration Docker container per runtime attempt."""

    def __init__(self, spec: SandboxSpec, store: "RunStore") -> None:
        self.spec = spec
        self.store = store
        self.proxy: EgressProxy | None = None
        self.container_name: str | None = None

    @property
    def docker(self) -> str:
        if self.spec.docker_path:
            return self.spec.docker_path
        found = shutil.which("docker")
        if not found:
            raise RuntimeErrorStateError("Docker executable not found")
        return found

    def _run(
        self,
        arguments: list[str],
        *,
        timeout: float = 15,
        check: bool = True,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            completed = subprocess.run(
                [self.docker, *arguments],
                check=False,
                capture_output=capture,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeErrorStateError(f"Docker command failed: {error}") from error
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeErrorStateError(
                f"Docker command failed with {completed.returncode}: {detail}"
            )
        return completed

    def verify_daemon_and_image(self) -> dict[str, Any]:
        version = self._run(["version", "--format", "{{json .Server}}"], timeout=5)
        image = self._run(
            ["image", "inspect", self.spec.image, "--format", "{{json .}}"],
            timeout=5,
        )
        return {
            "server": json.loads(version.stdout),
            "image": json.loads(image.stdout),
        }

    def prepare(
        self,
        run_id: str,
        contract: dict[str, Any],
        *,
        command: tuple[str, ...],
    ) -> dict[str, Any]:
        network = contract["boundaries"]["network"]
        allowlist = tuple(network.get("allowlist", []))
        if network["mode"] == "allowlist" and not allowlist:
            raise RuntimeErrorStateError("allowlist mode requires at least one destination")
        development_open = (
            network["mode"] == "development_open"
            or self.spec.network_profile == "development_open"
        )
        if self.spec.network_profile == "development_open" and network[
            "mode"
        ] != "development_open":
            raise RuntimeErrorStateError(
                "development_open sandbox profile requires a development_open contract"
            )

        run_root = self.store.run_root(run_id)
        workspace = run_root / "workspace"
        branch = self._workspace_branch(run_id, contract, workspace)
        evidence: dict[str, Any] = {
            "container_name": f"asdi-{run_id}",
            "container_id_file": str(run_root / "container.cid"),
            "workspace": str(workspace),
            "branch": branch,
            "image": self.spec.image,
            "network_mode": "bridge" if development_open else "none",
            "egress_mode": "development_open_noncompliant" if development_open else network["mode"],
            "isolation_compliant": False if development_open else True,
            "allowlist": list(allowlist),
        }
        if network["mode"] == "allowlist":
            # Darwin limits AF_UNIX addresses to 104 bytes; evidence roots may
            # be much deeper.  A short per-run path in the system temp dir is
            # still uniquely named and is unlinked by proxy shutdown/cleanup.
            socket_path = (
                Path(self.spec.egress_host_socket_dir) / f"asdi-{run_id}.sock"
            )
            self.proxy = EgressProxy(
                socket_path,
                allowlist,
                reporter=lambda decision, count: self._record_egress(
                    run_id, decision, count
                ),
            )
            self.proxy.start()
            evidence["egress_socket_host"] = str(socket_path)
            evidence["egress_socket_container"] = self.spec.egress_socket
        return evidence

    def docker_run_argv(
        self,
        run_id: str,
        evidence: dict[str, Any],
        runtime_command: tuple[str, ...],
    ) -> list[str]:
        run_root = self.store.run_root(run_id)
        workspace = run_root / "workspace"
        user = self.spec.container_user
        if user is None and hasattr(os, "getuid"):
            user = f"{os.getuid()}:{os.getgid()}"
        development_open = evidence["network_mode"] == "bridge"
        argv = [
            "run",
            "--name",
            str(evidence["container_name"]),
            "--pull",
            "never",
            "--cidfile",
            str(evidence["container_id_file"]),
            "--network",
            "bridge" if development_open else "none",
            "--init",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--memory",
            self.spec.memory,
            "--memory-swap",
            self.spec.memory,
            "--cpus",
            str(self.spec.cpus),
            "--pids-limit",
            str(self.spec.pids_limit),
        ]
        if user:
            argv.extend(("--user", user))
        argv.extend(
            (
                "--entrypoint",
                runtime_command[0],
                "--mount",
                f"type=bind,source={workspace},destination={self.spec.workspace_root}",
                "--workdir",
                self.spec.workspace_root,
                "--env",
                f"ASDI_RUN_ID={run_id}",
                "--env",
                f"ASDI_ALLOWED_BRANCH={evidence['branch']}",
                "--env",
                "ASDI_SANDBOX_MODE="
                + (
                    "container_development_open_noncompliant"
                    if development_open
                    else "container_network_none"
                ),
            )
        )
        if self.proxy is not None:
            argv.extend(
                (
                    "--mount",
                    f"type=bind,source={self.socket_path()},destination={self.spec.egress_socket}",
                    "--env",
                    f"ASDI_EGRESS_SOCKET={self.spec.egress_socket}",
                )
            )
        argv.extend((self.spec.image, *runtime_command[1:]))
        return argv

    def socket_path(self) -> Path:
        if self.proxy is None:
            raise RuntimeErrorStateError("egress proxy is not configured")
        return self.proxy.socket_path

    def wait_for_container(
        self,
        process: subprocess.Popen[str],
        timeout: float = 5,
    ) -> tuple[str, str]:
        assert self.container_name
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            container_id = ""
            cid_path = Path(self.run_id_cidfile_path())
            if cid_path.exists():
                container_id = cid_path.read_text(encoding="utf-8").strip()
            if process.poll() is not None:
                stdout = process.stdout.read() if process.stdout else ""
                stderr = process.stderr.read() if process.stderr else ""
                if not container_id:
                    raise RuntimeErrorStateError(
                        f"Docker run exited before container creation: "
                        f"{(stderr or stdout).strip()[:2_000]}"
                    )
                inspect = self._run(
                    [
                        "container",
                        "inspect",
                        container_id,
                        "--format",
                        "{{json .State}}",
                    ],
                    check=False,
                    timeout=2,
                )
                if inspect.returncode == 0:
                    state = json.loads(inspect.stdout)
                    if state.get("StartedAt"):
                        return str(state.get("StartedAt", "")), container_id
                raise RuntimeErrorStateError(
                    f"Docker container was not inspectable after creation: "
                    f"{(inspect.stderr or inspect.stdout or last_error).strip()[:2_000]}"
                )
            if container_id:
                inspect = self._run(
                    [
                        "container",
                        "inspect",
                        container_id,
                        "--format",
                        "{{json .State}}",
                    ],
                    check=False,
                    timeout=2,
                )
                if inspect.returncode == 0:
                    state = json.loads(inspect.stdout)
                    if state.get("Running") and state.get("StartedAt"):
                        return str(state.get("StartedAt", "")), container_id
                    last_error = str(state.get("Error", ""))
                time.sleep(0.02)
                continue
            time.sleep(0.05)
        raise RuntimeErrorStateError(
            f"container did not enter Running state: {last_error or 'timeout'}"
        )

    def container_id(self, container_name: str) -> str:
        completed = self._run(
            ["container", "inspect", container_name, "--format", "{{.Id}}"],
            timeout=3,
        )
        return completed.stdout.strip()

    def inspect_exit_state(self, container_name: str) -> dict[str, Any]:
        completed = self._run(
            [
                "container",
                "inspect",
                container_name,
                "--format",
                "{{json .State}}",
            ],
            check=False,
            timeout=3,
        )
        if completed.returncode != 0:
            return {"inspect_available": False}
        return json.loads(completed.stdout)

    def stop_container(self, container_name: str, *, timeout: float = 5) -> None:
        try:
            self._run(
                ["stop", "--time", str(max(1, min(int(timeout), self.spec.stop_timeout))), container_name],
                check=False,
                timeout=timeout + self.spec.stop_timeout,
            )
        finally:
            self._run(["rm", "--force", container_name], check=False, timeout=5)

    def cleanup(self, run_id: str, *, container_name: str | None = None) -> None:
        target = container_name or self.container_name
        if target:
            self.stop_container(target)
        if self.proxy is not None:
            self.proxy.stop()

    def done_check_container_name(self, run_id: str) -> str:
        return f"asdi-check-{uuid.uuid4().hex[:12]}"

    def done_check_argv(
        self,
        run_id: str,
        contract: dict[str, Any],
        *,
        container_name: str,
    ) -> list[str]:
        # A short-lived verification container uses the same image/workspace
        # and network=none.  It never sees host credentials or egress.
        run_root = self.store.run_root(run_id)
        workspace = run_root / "workspace"
        user = self.spec.container_user
        if user is None and hasattr(os, "getuid"):
            user = f"{os.getuid()}:{os.getgid()}"
        argv = [
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            container_name,
            "--network",
            "none",
            "--init",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--memory",
            self.spec.memory,
            "--memory-swap",
            self.spec.memory,
            "--cpus",
            str(self.spec.cpus),
            "--pids-limit",
            str(self.spec.pids_limit),
            "--entrypoint",
            contract["done_check"]["argv"][0],
            "--mount",
            f"type=bind,source={workspace},destination={self.spec.workspace_root}",
            "--workdir",
            self.spec.workspace_root,
            "--env",
            f"ASDI_RUN_ID={run_id}",
            "--env",
            "ASDI_SANDBOX_MODE=container_done_check",
        ]
        if user:
            argv.extend(("--user", user))
        argv.extend((self.spec.image, *contract["done_check"]["argv"][1:]))
        return argv

    def remove_container(self, container_name: str) -> None:
        self._run(["rm", "--force", container_name], check=False, timeout=5)

    def run_id_cidfile_path(self) -> str:
        assert self.container_name
        run_id = self.container_name.removeprefix("asdi-")
        return str(self.store.run_root(run_id) / "container.cid")

    def _workspace_branch(
        self,
        run_id: str,
        contract: dict[str, Any],
        workspace: Path,
    ) -> str:
        output = contract["output"]
        branch = (
            output["branch"]
            if output["kind"] == "pull_request"
            else f"asdi/run/{run_id.removeprefix('asdi_run_').replace('-', '')[:30]}"
        )
        try:
            subprocess.run(
                ["git", "init", "--initial-branch", branch, str(workspace)],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            subprocess.run(
                ["git", "config", "user.name", "ASDI Isolated Run"],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            subprocess.run(
                ["git", "config", "user.email", f"{run_id}@invalid"],
                cwd=workspace,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeErrorStateError(f"workspace branch setup failed: {error}") from error
        return branch

    def _record_egress(
        self, run_id: str, decision: EgressDecision, bytes_relayed: int
    ) -> None:
        self.store.append_event(
            run_id,
            "egress_decision",
            {
                "allowed": decision.allowed,
                "host": decision.host,
                "port": decision.port,
                "reason": decision.reason,
                "addresses": list(decision.addresses),
                "bytes_relayed": bytes_relayed,
                "observed_at": utc_now(),
            },
        )
