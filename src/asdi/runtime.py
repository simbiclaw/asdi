"""Board-neutral run identity, process launcher, and runtime adapters.

This module is the ASDI-011 execution kernel boundary.  It does not integrate a
board and it does not provide the ASDI-012 container boundary.  Production
runtime adapters deliberately fail closed until that boundary exists; the
synthetic local-process adapter exists to test process lifecycle behavior only.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import ctypes
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import RuntimeErrorStateError
from .run_contract import validate_run_contract
from .sandbox import ContainerSandbox, SandboxSpec


RUN_STATE_SCHEMA_VERSION = "asdi.run-state/v1"
RUN_EVENT_SCHEMA_VERSION = "asdi.run-event/v1"
TERMINAL_RUN_STATUSES = {
    "succeeded",
    "failed",
    "cancelled",
    "blocked",
}
NON_COMPLIANT_TEST_ADAPTERS = {"local_process_test"}


__all__ = ["RuntimeErrorStateError"]


@dataclass(frozen=True)
class RuntimeAdapterConfig:
    """Explicit runtime invocation configuration.

    Command templates are deliberately explicit.  ASDI does not silently
    construct shell strings or infer a vendor CLI's product interface.
    """

    executable_path: str | None = None
    container_executable_path: str | None = None
    argv_prefix: tuple[str, ...] = ()
    argv_suffix: tuple[str, ...] = ()
    include_objective: bool = True


class RuntimeAdapter:
    """Interface implemented by every runtime adapter."""

    name: str = "abstract"
    executable_names: tuple[str, ...] = ()
    done_check_recheck: bool = True
    development_safe: bool = False

    def resolve_executable(
        self, config: RuntimeAdapterConfig
    ) -> str | None:
        if config.executable_path is not None:
            path = Path(config.executable_path)
            if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
                return str(path)
            return None
        for name in self.executable_names:
            found = shutil.which(name)
            if found:
                return found
        return None

    def build_command(
        self,
        contract: dict[str, Any],
        executable: str,
        config: RuntimeAdapterConfig,
    ) -> tuple[str, ...]:
        objective_arguments = (contract["objective"],) if config.include_objective else ()
        command = (
            executable,
            *config.argv_prefix,
            *objective_arguments,
            *config.argv_suffix,
        )
        self.validate_runtime_command(command)
        return command

    def validate_runtime_command(self, command: tuple[str, ...]) -> None:
        if not command or not Path(command[0]).is_absolute():
            raise RuntimeErrorStateError("runtime executable must be an absolute path")
        executable_name = Path(command[0]).name.lower()
        forbidden_launchers = {"archon", "asdi", "asdi-launcher"}
        shell_interpreters = {"sh", "bash", "dash", "zsh", "ksh"}
        if executable_name in forbidden_launchers:
            raise RuntimeErrorStateError("nested orchestration is forbidden")
        if executable_name in shell_interpreters:
            raise RuntimeErrorStateError("shell-interpreter runtime commands are forbidden")
        for argument in command[1:]:
            if not isinstance(argument, str) or any(ord(char) < 32 for char in argument):
                raise RuntimeErrorStateError("runtime arguments must be printable strings")


class ClaudeCodeAdapter(RuntimeAdapter):
    """Claude Code adapter; H2 relies on its Stop-hook evidence."""

    name = "claude_code"
    executable_names = ("claude",)
    done_check_recheck = False


class CodexAdapter(RuntimeAdapter):
    """Codex adapter; the launcher independently reruns done_check."""

    name = "codex"
    executable_names = ("codex",)
    done_check_recheck = True


class HermesAdapter(RuntimeAdapter):
    """Hermes adapter; the launcher independently reruns done_check."""

    name = "hermes"
    executable_names = ("hermes",)
    done_check_recheck = True


class LocalProcessTestAdapter(RuntimeAdapter):
    """Synthetic adapter used only for controlled process-lifecycle tests.

    It accepts a small allowlist of absolute system utilities and is explicitly
    marked non-compliant with H3.  It must never be used for autonomous work.
    """

    name = "local_process_test"
    executable_names = ()
    done_check_recheck = True
    development_safe = True
    allowed_utilities = {"echo", "false", "pwd", "sleep", "true"}

    def validate_runtime_command(self, command: tuple[str, ...]) -> None:
        super().validate_runtime_command(command)
        utility = Path(command[0]).name.lower()
        if utility not in self.allowed_utilities:
            raise RuntimeErrorStateError(
                f"synthetic process adapter forbids utility {utility!r}"
            )


ADAPTERS: dict[str, RuntimeAdapter] = {
    adapter.name: adapter
    for adapter in (
        ClaudeCodeAdapter(),
        CodexAdapter(),
        HermesAdapter(),
        LocalProcessTestAdapter(),
    )
}


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class _MacProcessBsdInfo(ctypes.Structure):
    """Darwin sys/proc_info.h proc_bsdinfo layout."""

    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("xstatus", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("ppid", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32),
        ("svuid", ctypes.c_uint32),
        ("svgid", ctypes.c_uint32),
        ("rfu", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32),
        ("pgid", ctypes.c_uint32),
        ("pjobc", ctypes.c_uint32),
        ("tdev", ctypes.c_uint32),
        ("tpgid", ctypes.c_uint32),
        ("nice", ctypes.c_int32),
        ("start_tvsec", ctypes.c_uint64),
        ("start_tvusec", ctypes.c_uint64),
    ]


def process_start_time(pid: int) -> str | None:
    """Return the host's stable process-birth identity, when available.

    Darwin exposes the birth time through libproc without spawning a process.
    Unsupported platforms intentionally return ``None`` so launcher startup
    fails closed rather than accepting a reusable PID as durable identity.
    """

    if sys.platform != "darwin":
        return None
    info = _MacProcessBsdInfo()
    library = ctypes.CDLL(None, use_errno=True)
    returned = library.proc_pidinfo(
        pid,
        3,  # PROC_PIDTBSDINFO
        0,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if returned != ctypes.sizeof(info) or info.pid != pid:
        return None
    return f"{info.start_tvsec}:{info.start_tvusec:06d}"


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def signal_name(number: int | None) -> str | None:
    if number is None:
        return None
    try:
        return signal.Signals(-number).name
    except (ValueError, AttributeError):
        return f"signal_{-number}"


class RunStore:
    """Durable per-run JSON state and append-only JSONL event log."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def run_root(self, run_id: str) -> Path:
        if not run_id.startswith("asdi_run_") or any(char in run_id for char in "/\\"):
            raise RuntimeErrorStateError("invalid run identity")
        return self.root / "runs" / run_id

    def _atomic_write(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def create_run(
        self,
        contract: dict[str, Any],
        *,
        board_task_reference: str | None = None,
    ) -> dict[str, Any]:
        run_id = f"asdi_run_{uuid.uuid4()}"
        run_root = self.run_root(run_id)
        if run_root.exists():
            raise RuntimeErrorStateError("run identity collision")
        now = utc_now()
        state: dict[str, Any] = {
            "schema_version": RUN_STATE_SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": now,
            "updated_at": now,
            "status": "created",
            "board_task_reference": board_task_reference,
            "contract": contract,
            "runtime": None,
            "process": None,
            "usage": None,
            "done_check": None,
            "result": None,
            "isolation_compliant": False,
            "isolation_mode": None,
            "cancel_requested": False,
            "event_sequence": 0,
        }
        run_root.mkdir(parents=True)
        workspace = run_root / "workspace"
        workspace.mkdir()
        (workspace / ".asdi_run_id").write_text(f"{run_id}\n", encoding="utf-8")
        self._atomic_write(run_root / "run.json", state)
        self.append_event(run_id, "run_created", {"status": "created"})
        self.append_event(
            run_id,
            "contract_validated",
            {"schema_version": contract["schema_version"]},
        )
        return state

    def load_run(self, run_id: str) -> dict[str, Any]:
        path = self.run_root(run_id) / "run.json"
        try:
            with path.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        except FileNotFoundError as error:
            raise RuntimeErrorStateError(f"run not found: {run_id}") from error
        if state.get("schema_version") != RUN_STATE_SCHEMA_VERSION:
            raise RuntimeErrorStateError("unsupported run-state schema")
        if state.get("run_id") != run_id:
            raise RuntimeErrorStateError("run identity mismatch")
        return state

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            state = self.load_run(run_id)
            state["event_sequence"] = int(state.get("event_sequence", 0)) + 1
            event = {
                "schema_version": RUN_EVENT_SCHEMA_VERSION,
                "sequence": state["event_sequence"],
                "run_id": run_id,
                "timestamp": utc_now(),
                "type": event_type,
                "payload": payload,
            }
            path = self.run_root(run_id) / "events.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._atomic_write(self.run_root(run_id) / "run.json", state)
            return event

    def transition(
        self,
        run_id: str,
        updates: dict[str, Any],
        expected_statuses: set[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = self.load_run(run_id)
            if expected_statuses is not None and state["status"] not in expected_statuses:
                raise RuntimeErrorStateError(
                    f"run {run_id} is {state['status']}; expected one of "
                    f"{', '.join(sorted(expected_statuses))}"
                )
            state.update(updates)
            state["updated_at"] = utc_now()
            self._atomic_write(self.run_root(run_id) / "run.json", state)
            return state

    def events(self, run_id: str) -> list[dict[str, Any]]:
        path = self.run_root(run_id) / "events.jsonl"
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    events.append(json.loads(line))
        return events


@dataclass
class ProcessHandle:
    run_id: str
    pid: int | None
    process_start_time: str | None
    process: subprocess.Popen[str] | None = None
    readers: list[Any] | None = None
    store: RunStore | None = None
    adapter: RuntimeAdapter | None = None
    contract: dict[str, Any] | None = None
    workspace: Path | None = None
    sandbox: ContainerSandbox | None = None
    container_name: str | None = None
    container_id: str | None = None
    cancel_requested: bool = False

    def is_running(self) -> bool:
        if self.process is not None:
            return self.process.poll() is None
        return self.pid is not None and process_alive(self.pid)

    def wait(self, timeout: float | None = None) -> dict[str, Any]:
        assert self.store is not None
        assert self.adapter is not None
        assert self.contract is not None
        assert self.workspace is not None
        deadline = None if timeout is None else time.monotonic() + timeout
        if self.process is not None:
            self.process.wait()
            if self.readers:
                for reader in self.readers:
                    reader.join(timeout=5)
                still_reading = any(reader.is_alive() for reader in self.readers)
                if still_reading:
                    self.store.append_event(
                        self.run_id,
                        "event_collection_incomplete",
                        {"reader_threads_alive": True},
                    )
        else:
            while self.is_running():
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for run {self.run_id}")
                time.sleep(0.05)

        state = self.store.load_run(self.run_id)
        if self.process is None:
            self._fail(
                "host_restart_exit_unknown",
                "a recovered process exited without a durable exit-code record",
            )
            return self.store.load_run(self.run_id)
        if state["status"] == "cancelling":
            self._finish_cancelled()
            self._cleanup_sandbox()
            return self.store.load_run(self.run_id)
        if state["status"] != "running":
            self._cleanup_sandbox()
            return state
        self._record_exit()
        state = self.store.load_run(self.run_id)
        if state["status"] != "runtime_succeeded":
            self._cleanup_sandbox()
            return state
        if self.adapter.done_check_recheck:
            return self._run_done_check()
        if self._runtime_reported_done_check():
            self.store.transition(
                self.run_id,
                {
                    "status": "succeeded",
                    "result": {
                        "kind": "success",
                        "done_check_source": "runtime_stop_hook",
                        "finished_at": utc_now(),
                    },
                },
                expected_statuses={"runtime_succeeded"},
            )
            self.store.append_event(
                self.run_id,
                "run_succeeded",
                {"done_check_source": "runtime_stop_hook"},
            )
        else:
            self._fail(
                "done_check_unverified",
                "runtime exited successfully but produced no Stop-hook pass evidence",
            )
        self._cleanup_sandbox()
        return self.store.load_run(self.run_id)

    def cancel(self, timeout: float = 5.0) -> dict[str, Any]:
        assert self.store is not None
        state = self.store.load_run(self.run_id)
        if state["status"] in TERMINAL_RUN_STATUSES:
            return state
        if not state.get("cancel_requested"):
            self.store.transition(
                self.run_id,
                {"status": "cancelling", "cancel_requested": True},
                expected_statuses={"created", "starting", "running"},
            )
            self.store.append_event(
                self.run_id, "cancel_requested", {"signal": "SIGTERM"}
            )
        self.cancel_requested = True
        if self.pid is None:
            raise RuntimeErrorStateError("cannot cancel a run without a process identity")
        try:
            if self.process is not None:
                self.process.send_signal(signal.SIGTERM)
            else:
                os.kill(self.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError) as error:
            self.store.append_event(
                self.run_id,
                "cancel_signal_failed",
                {"signal": "SIGTERM", "error": str(error)},
            )
            raise
        deadline = time.monotonic() + timeout
        while self.is_running() and time.monotonic() < deadline:
            time.sleep(0.05)
        if self.is_running():
            self.store.append_event(
                self.run_id,
                "cancel_escalated",
                {"signal": "SIGKILL", "reason": "SIGTERM timeout"},
            )
            try:
                if self.process is not None:
                    self.process.kill()
                else:
                    os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.process is not None:
            self.process.wait()
            if self.readers:
                for reader in self.readers:
                    reader.join(timeout=2)
        else:
            while self.is_running():
                time.sleep(0.05)
        final = self._finish_cancelled()
        self._cleanup_sandbox()
        return final

    def _finish_cancelled(self) -> dict[str, Any]:
        assert self.store is not None
        if self.process is not None:
            returncode = self.process.returncode
        else:
            returncode = None
        self.store.transition(
            self.run_id,
            {
                "status": "cancelled",
                "result": {
                    "kind": "cancelled",
                    "exit_code": returncode,
                    "signal": signal_name(returncode),
                    "finished_at": utc_now(),
                },
            },
            expected_statuses={"cancelling"},
        )
        self.store.append_event(
            self.run_id,
            "process_cancelled",
            {"exit_code": returncode, "signal": signal_name(returncode)},
        )
        return self.store.load_run(self.run_id)

    def _cleanup_sandbox(self) -> None:
        if self.sandbox is None:
            return
        try:
            self.sandbox.cleanup(
                self.run_id,
                container_name=self.container_name,
            )
            if self.container_name is not None:
                self.store.append_event(
                    self.run_id,
                    "container_cleaned",
                    {"container_name": self.container_name},
                )
        except RuntimeErrorStateError as error:
            self.store.append_event(
                self.run_id,
                "container_cleanup_failed",
                {
                    "container_name": self.container_name,
                    "error": str(error),
                },
            )
            raise

    def _record_exit(self) -> None:
        assert self.process is not None
        assert self.store is not None
        returncode = self.process.returncode
        payload = {
            "exit_code": returncode,
            "signal": signal_name(returncode),
            "finished_at": utc_now(),
        }
        if self.sandbox is not None and self.container_name is not None:
            payload["container_state"] = self.sandbox.inspect_exit_state(
                self.container_name
            )
        self.store.append_event(self.run_id, "process_exit", payload)
        if returncode == 0:
            self.store.transition(
                self.run_id,
                {"status": "runtime_succeeded", "result": {"kind": "runtime_success"}},
                expected_statuses={"running"},
            )
        else:
            self.store.transition(
                self.run_id,
                {
                    "status": "failed",
                    "result": {
                        "kind": "runtime_failure",
                        "reason": "runtime_failure",
                        **payload,
                    },
                },
                expected_statuses={"running"},
            )
            self.store.append_event(
                self.run_id,
                "run_failed",
                {"reason": "runtime_nonzero_exit", **payload},
            )

    def _runtime_reported_done_check(self) -> bool:
        assert self.store is not None
        for event in self.store.events(self.run_id):
            if event.get("type") != "runtime_output":
                continue
            payload = event.get("payload", {})
            structured = payload.get("structured")
            if not isinstance(structured, dict):
                continue
            marker = structured.get("done_check", structured.get("stop_hook"))
            if isinstance(marker, dict) and marker.get("status") in {
                "passed",
                "success",
            }:
                return True
            if marker in {"passed", "success"}:
                return True
        return False

    def _run_done_check(self) -> dict[str, Any]:
        assert self.store is not None
        assert self.contract is not None
        assert self.workspace is not None
        done_check = self.contract["done_check"]
        timeout = done_check.get(
            "timeout_seconds", self.contract["guardrails"]["wall_clock_seconds"]
        )
        stdout_path = self.store.run_root(self.run_id) / "done_check.stdout.log"
        stderr_path = self.store.run_root(self.run_id) / "done_check.stderr.log"
        self.store.transition(
            self.run_id,
            {
                "status": "done_check_running",
                "done_check": {
                    "argv": done_check["argv"],
                    "started_at": utc_now(),
                    "stdout_path": stdout_path.name,
                    "stderr_path": stderr_path.name,
                },
            },
            expected_statuses={"runtime_succeeded"},
        )
        self.store.append_event(
            self.run_id,
            "done_check_started",
            {"argv": done_check["argv"]},
        )
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                if self.sandbox is not None:
                    check_container = self.sandbox.done_check_container_name(
                        self.run_id
                    )
                    completed = subprocess.run(
                        [
                            self.sandbox.docker,
                            *self.sandbox.done_check_argv(
                                self.run_id,
                                self.contract,
                                container_name=check_container,
                            ),
                        ],
                        stdout=stdout,
                        stderr=stderr,
                        stdin=subprocess.DEVNULL,
                        timeout=timeout,
                        check=False,
                    )
                    self.sandbox.remove_container(check_container)
                else:
                    completed = subprocess.run(
                        done_check["argv"],
                        cwd=self.workspace,
                        stdout=stdout,
                        stderr=stderr,
                        stdin=subprocess.DEVNULL,
                        env=_safe_environment(self.run_id, "done_check"),
                        timeout=timeout,
                        check=False,
                    )
        except FileNotFoundError as error:
            self._fail(
                "done_check_missing",
                f"done-check executable could not be run: {error}",
                done_check_files=(stdout_path.name, stderr_path.name),
            )
            self._cleanup_sandbox()
            return self.store.load_run(self.run_id)
        except subprocess.TimeoutExpired:
            if self.sandbox is not None:
                # Killing the Docker CLI on timeout does not necessarily stop
                # the already-created verification container. Remove it by the
                # identity captured before launch so no check container leaks.
                try:
                    self.sandbox.remove_container(check_container)
                except RuntimeErrorStateError:
                    pass
            self._fail(
                "done_check_timeout",
                f"done_check exceeded {timeout} seconds",
                done_check_files=(stdout_path.name, stderr_path.name),
            )
            self._cleanup_sandbox()
            return self.store.load_run(self.run_id)

        exit_code = completed.returncode
        self.store.transition(
            self.run_id,
            {
                "done_check": {
                    "argv": done_check["argv"],
                    "started_at": utc_now(),
                    "finished_at": utc_now(),
                    "exit_code": exit_code,
                    "stdout_path": stdout_path.name,
                    "stderr_path": stderr_path.name,
                }
            },
            expected_statuses={"done_check_running"},
        )
        self.store.append_event(
            self.run_id,
            "done_check_exit",
            {
                "exit_code": exit_code,
                "stdout_path": stdout_path.name,
                "stderr_path": stderr_path.name,
            },
        )
        if exit_code == 0:
            self.store.transition(
                self.run_id,
                {
                    "status": "succeeded",
                    "result": {
                        "kind": "success",
                        "done_check_source": "launcher_recheck",
                        "finished_at": utc_now(),
                    },
                },
                expected_statuses={"done_check_running"},
            )
            self.store.append_event(
                self.run_id,
                "run_succeeded",
                {"done_check_source": "launcher_recheck", "exit_code": 0},
            )
        else:
            self._fail(
                "done_check_failed",
                f"done_check exited with code {exit_code}",
                done_check_files=(stdout_path.name, stderr_path.name),
            )
        self._cleanup_sandbox()
        return self.store.load_run(self.run_id)

    def _fail(
        self,
        reason: str,
        message: str,
        *,
        done_check_files: tuple[str, str] | None = None,
    ) -> None:
        assert self.store is not None
        result: dict[str, Any] = {
            "kind": "failure",
            "reason": reason,
            "message": message,
            "finished_at": utc_now(),
        }
        if done_check_files:
            result["stdout_path"] = done_check_files[0]
            result["stderr_path"] = done_check_files[1]
        self.store.transition(self.run_id, {"status": "failed", "result": result})
        self.store.append_event(
            self.run_id,
            "run_failed",
            {"reason": reason, "message": message},
        )


def _safe_environment(run_id: str, purpose: str) -> dict[str, str]:
    """Expose run identity only; never forward the launcher environment."""

    return {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "ASDI_RUN_ID": run_id,
        "ASDI_PROCESS_PURPOSE": purpose,
        "ASDI_SANDBOX_MODE": "none_noncompliant",
    }


class RunLauncher:
    """Create, start, cancel, recover, and observe durable local runs."""

    def __init__(self, store: RunStore) -> None:
        self.store = store

    def create_run(
        self,
        contract: dict[str, Any],
        *,
        board_task_reference: str | None = None,
    ) -> dict[str, Any]:
        validated = validate_run_contract(contract)
        return self.store.create_run(
            validated,
            board_task_reference=board_task_reference,
        )

    def start_runtime(
        self,
        run_id: str,
        adapter_name: str,
        config: RuntimeAdapterConfig,
        *,
        isolation_mode: str,
        allow_noncompliant_test: bool = False,
        sandbox_spec: SandboxSpec | None = None,
    ) -> ProcessHandle:
        state = self.store.load_run(run_id)
        if state["status"] != "created":
            raise RuntimeErrorStateError(
                f"run {run_id} is {state['status']}, not created"
            )
        try:
            contract = validate_run_contract(state["contract"])
        except ValueError as error:
            self.store.transition(
                run_id,
                {
                    "status": "failed",
                    "result": {
                        "kind": "failure",
                        "reason": "invalid_contract",
                        "message": str(error),
                        "finished_at": utc_now(),
                    },
                },
                expected_statuses={"created"},
            )
            self.store.append_event(
                run_id, "run_failed", {"reason": "invalid_contract"}
            )
            raise RuntimeErrorStateError(str(error)) from error

        adapter = ADAPTERS.get(adapter_name)
        if adapter is None:
            self._start_failure(
                run_id,
                adapter_name,
                isolation_mode,
                "unknown_runtime",
                f"runtime adapter {adapter_name!r} is not registered",
            )
            raise RuntimeErrorStateError(f"unknown runtime adapter {adapter_name!r}")

        executable = None
        if not (isolation_mode == "container" and config.container_executable_path):
            try:
                executable = adapter.resolve_executable(config)
            except OSError as error:
                self._start_failure(
                    run_id,
                    adapter_name,
                    isolation_mode,
                    "runtime_probe_failed",
                    str(error),
                )
                raise RuntimeErrorStateError(str(error)) from error
            if executable is None:
                searched = config.executable_path or ", ".join(adapter.executable_names)
                self._start_failure(
                    run_id,
                    adapter_name,
                    isolation_mode,
                    "missing_runtime",
                    f"runtime executable not found: {searched}",
                )
                raise RuntimeErrorStateError(
                    f"runtime executable not found: {searched}"
                )
        if isolation_mode == "container":
            if sandbox_spec is None:
                self._start_failure(
                    run_id,
                    adapter_name,
                    isolation_mode,
                    "sandbox_not_configured",
                    "container execution requires an explicit trusted image and runtime path",
                )
                raise RuntimeErrorStateError(
                    "container execution requires an explicit sandbox specification"
                )
            if not config.container_executable_path:
                self._start_failure(
                    run_id,
                    adapter_name,
                    isolation_mode,
                    "missing_container_runtime_path",
                    "container execution requires an absolute in-container runtime executable",
                )
                raise RuntimeErrorStateError(
                    "container execution requires a container runtime executable path"
                )
            command = adapter.build_command(
                contract,
                config.container_executable_path,
                config,
            )
            sandbox = ContainerSandbox(sandbox_spec, self.store)
            try:
                sandbox.verify_daemon_and_image()
                evidence = sandbox.prepare(
                    run_id,
                    contract,
                    command=command,
                )
                docker_argv = sandbox.docker_run_argv(
                    run_id,
                    evidence,
                    command,
                )
                sandbox.container_name = str(evidence["container_name"])
                self.store.transition(
                    run_id,
                    {
                        "status": "starting",
                        "runtime": {
                            "adapter": adapter_name,
                            "executable": config.container_executable_path,
                            "argv": list(command),
                        },
                        "isolation_compliant": True,
                        "isolation_mode": "container_network_none",
                        "sandbox": evidence,
                    },
                    expected_statuses={"created"},
                )
                self.store.append_event(
                    run_id,
                    "runtime_starting",
                    {
                        "adapter": adapter_name,
                        "isolation": "container_network_none",
                        "argv": list(command),
                        "sandbox": evidence,
                    },
                )
                run_root = self.store.run_root(run_id)
                process = subprocess.Popen(
                    [sandbox.docker, *docker_argv],
                    cwd=run_root.parent,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
                started_at, container_id = sandbox.wait_for_container(process)
                self.store.transition(
                    run_id,
                    {
                        "status": "running",
                        "process": {
                            "pid": process.pid,
                            "process_start_time": process_start_time(process.pid),
                            "container_name": sandbox.container_name,
                            "container_id": container_id,
                            "container_started_at": started_at,
                        },
                        "started_at": utc_now(),
                    },
                    expected_statuses={"starting"},
                )
                self.store.append_event(
                    run_id,
                    "runtime_started",
                    {
                        "pid": process.pid,
                        "container_name": sandbox.container_name,
                        "container_id": container_id,
                        "container_started_at": started_at,
                    },
                )
                readers = [
                    self._start_output_reader(
                        run_id,
                        process.stdout,
                        "stdout",
                        run_root / "stdout.log",
                    ),
                    self._start_output_reader(
                        run_id,
                        process.stderr,
                        "stderr",
                        run_root / "stderr.log",
                    ),
                ]
                return ProcessHandle(
                    run_id=run_id,
                    pid=process.pid,
                    process_start_time=process_start_time(process.pid),
                    process=process,
                    readers=readers,
                    store=self.store,
                    adapter=adapter,
                    contract=contract,
                    workspace=run_root / "workspace",
                    sandbox=sandbox,
                    container_name=sandbox.container_name,
                    container_id=container_id,
                )
            except RuntimeErrorStateError as error:
                if sandbox.container_name is not None:
                    try:
                        sandbox.stop_container(sandbox.container_name)
                    except RuntimeErrorStateError:
                        pass
                if sandbox.proxy is not None:
                    sandbox.proxy.stop()
                self._start_failure(
                    run_id,
                    adapter_name,
                    isolation_mode,
                    "sandbox_setup_failed",
                    str(error),
                    command=command,
                )
                raise
        if isolation_mode != "host_process_test":
            self._start_failure(
                run_id,
                adapter_name,
                isolation_mode,
                "unknown_isolation_mode",
                f"isolation mode {isolation_mode!r} is unsupported",
                command=command,
            )
            raise RuntimeErrorStateError(
                f"unsupported isolation mode {isolation_mode!r}"
            )
        if not allow_noncompliant_test or not adapter.development_safe:
            self._start_failure(
                run_id,
                adapter_name,
                isolation_mode,
                "unsafe_start_blocked",
                "host-process execution requires the synthetic adapter and explicit test authorization",
                command=command,
            )
            raise RuntimeErrorStateError(
                "host-process execution is prohibited without explicit synthetic-test authorization"
            )
        try:
            command = adapter.build_command(contract, executable, config)
        except RuntimeErrorStateError as error:
            self._start_failure(
                run_id,
                adapter_name,
                isolation_mode,
                "invalid_runtime_configuration",
                str(error),
            )
            raise

        run_root = self.store.run_root(run_id)
        workspace = run_root / "workspace"
        stdout_path = run_root / "stdout.log"
        stderr_path = run_root / "stderr.log"
        self.store.transition(
            run_id,
            {
                "status": "starting",
                "runtime": {
                    "adapter": adapter_name,
                    "executable": executable,
                    "argv": list(command),
                },
                "isolation_compliant": False,
                "isolation_mode": "host_process_test_noncompliant",
            },
            expected_statuses={"created"},
        )
        self.store.append_event(
            run_id,
            "runtime_starting",
            {
                "adapter": adapter_name,
                "isolation": "host_process_test_noncompliant",
                "argv": list(command),
            },
        )
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=_safe_environment(run_id, "runtime"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as error:
            self._start_failure(
                run_id,
                adapter_name,
                isolation_mode,
                "runtime_start_failed",
                str(error),
                command=command,
            )
            raise RuntimeErrorStateError(str(error)) from error

        start_time = process_start_time(process.pid)
        if start_time is None:
            process.kill()
            process.wait()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            self._start_failure(
                run_id,
                adapter_name,
                isolation_mode,
                "process_identity_unverifiable",
                "host did not provide a stable process start identity",
                command=command,
                pid=process.pid,
            )
            raise RuntimeErrorStateError("process identity is unverifiable")

        self.store.transition(
            run_id,
            {
                "status": "running",
                "process": {
                    "pid": process.pid,
                    "process_group": process.pid,
                    "process_start_time": start_time,
                },
                "started_at": utc_now(),
            },
            expected_statuses={"starting"},
        )
        self.store.append_event(
            run_id,
            "runtime_started",
            {
                "pid": process.pid,
                "process_group": process.pid,
                "process_start_time": start_time,
            },
        )
        readers = [
            self._start_output_reader(
                run_id,
                process.stdout,
                "stdout",
                stdout_path,
            ),
            self._start_output_reader(
                run_id,
                process.stderr,
                "stderr",
                stderr_path,
            ),
        ]
        return ProcessHandle(
            run_id=run_id,
            pid=process.pid,
            process_start_time=start_time,
            process=process,
            readers=readers,
            store=self.store,
            adapter=adapter,
            contract=contract,
            workspace=workspace,
        )

    def _start_output_reader(
        self,
        run_id: str,
        stream: Any,
        stream_name: str,
        raw_path: Path,
    ) -> Any:
        import threading

        def read_stream() -> None:
            if stream is None:
                return
            try:
                with raw_path.open("wb") as raw:
                    for line in iter(stream.readline, ""):
                        encoded = line.encode("utf-8", errors="replace")
                        raw.write(encoded)
                        raw.flush()
                        rendered = line.rstrip("\r\n")
                        truncated = len(rendered.encode("utf-8")) > 8_000
                        rendered = rendered[:8_000]
                        structured = None
                        stripped = rendered.strip()
                        if stripped.startswith("{") and stripped.endswith("}"):
                            try:
                                structured = json.loads(stripped)
                            except json.JSONDecodeError:
                                structured = None
                        payload: dict[str, Any] = {
                            "stream": stream_name,
                            "text": rendered,
                            "truncated": truncated,
                        }
                        if structured is not None:
                            payload["structured"] = structured
                            usage = structured.get("usage")
                            if isinstance(usage, dict):
                                self.store.transition(
                                    run_id,
                                    {
                                        "usage": {
                                            **usage,
                                            "observed_at": utc_now(),
                                            "source": "runtime_output",
                                        }
                                    },
                                    expected_statuses={"running", "runtime_succeeded"},
                                )
                                self.store.append_event(
                                    run_id,
                                    "usage_observed",
                                    {"usage": usage, "stream": stream_name},
                                )
                        self.store.append_event(
                            run_id, "runtime_output", payload
                        )
            except Exception as error:  # reader failure is evidence, not silence
                self.store.append_event(
                    run_id,
                    "event_collection_error",
                    {"stream": stream_name, "error": str(error)},
                )
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        reader = threading.Thread(
            target=read_stream,
            name=f"asdi-{run_id}-{stream_name}",
            daemon=True,
        )
        reader.start()
        return reader

    def _start_failure(
        self,
        run_id: str,
        adapter_name: str,
        isolation_mode: str,
        reason: str,
        message: str,
        *,
        command: tuple[str, ...] | None = None,
        pid: int | None = None,
    ) -> None:
        result: dict[str, Any] = {
            "kind": "failure",
            "reason": reason,
            "message": message,
            "adapter": adapter_name,
            "isolation_mode": isolation_mode,
            "finished_at": utc_now(),
        }
        if command is not None:
            result["argv"] = list(command)
        if pid is not None:
            result["pid"] = pid
        self.store.transition(
            run_id,
            {
                "status": "failed",
                "runtime": {
                    "adapter": adapter_name,
                    "executable": command[0] if command else None,
                    "argv": list(command) if command else None,
                },
                "isolation_mode": isolation_mode,
                "isolation_compliant": False,
                "result": result,
            },
            expected_statuses={"created", "starting"},
        )
        self.store.append_event(
            run_id,
            "run_failed",
            {
                "reason": reason,
                "message": message,
                "adapter": adapter_name,
                "isolation_mode": isolation_mode,
            },
        )

    def recover_run(self, run_id: str) -> dict[str, Any]:
        state = self.store.load_run(run_id)
        status = state["status"]
        if status in TERMINAL_RUN_STATUSES:
            return state
        if status == "created":
            return state

        process_info = state.get("process")
        if status in {"done_check_running", "runtime_succeeded"}:
            self.store.transition(
                run_id,
                {
                    "status": "failed",
                    "result": {
                        "kind": "failure",
                        "reason": "host_restart_interrupted",
                        "message": f"cannot resume incomplete status {status!r}",
                        "finished_at": utc_now(),
                    },
                },
            )
            self.store.append_event(
                run_id,
                "recovery_failed",
                {"reason": "host_restart_interrupted", "previous_status": status},
            )
            return self.store.load_run(run_id)
        if not isinstance(process_info, dict) or not isinstance(
            process_info.get("pid"), int
        ):
            return self._recovery_failure(run_id, status, "missing_process_identity")

        pid = process_info["pid"]
        persisted_start = process_info.get("process_start_time")
        if not process_alive(pid):
            self.store.transition(
                run_id,
                {
                    "status": "failed",
                    "result": {
                        "kind": "failure",
                        "reason": "host_restart_orphaned",
                        "message": "persisted process no longer exists",
                        "pid": pid,
                        "finished_at": utc_now(),
                    },
                },
            )
            self.store.append_event(
                run_id,
                "recovery_failed",
                {
                    "reason": "host_restart_orphaned",
                    "pid": pid,
                    "previous_status": status,
                },
            )
            return self.store.load_run(run_id)

        current_start = process_start_time(pid)
        if persisted_start is None or current_start != persisted_start:
            self.store.transition(
                run_id,
                {
                    "status": "failed",
                    "result": {
                        "kind": "failure",
                        "reason": "process_identity_changed",
                        "message": "persisted process identity does not match the host process",
                        "pid": pid,
                        "finished_at": utc_now(),
                    },
                },
            )
            self.store.append_event(
                run_id,
                "recovery_failed",
                {
                    "reason": "process_identity_changed",
                    "pid": pid,
                    "previous_status": status,
                },
            )
            return self.store.load_run(run_id)

        self.store.transition(
            run_id,
            {"status": status, "recovered_at": utc_now()},
        )
        self.store.append_event(
            run_id,
            "run_recovered",
            {"pid": pid, "process_start_time": current_start},
        )
        return state

    def _recovery_failure(
        self, run_id: str, previous_status: str, reason: str
    ) -> dict[str, Any]:
        self.store.transition(
            run_id,
            {
                "status": "failed",
                "result": {
                    "kind": "failure",
                    "reason": reason,
                    "message": "durable process identity cannot be recovered",
                    "previous_status": previous_status,
                    "finished_at": utc_now(),
                },
            },
        )
        self.store.append_event(
            run_id,
            "recovery_failed",
            {"reason": reason, "previous_status": previous_status},
        )
        return self.store.load_run(run_id)

    def attach_run(
        self,
        run_id: str,
        adapter_name: str,
    ) -> ProcessHandle:
        state = self.store.load_run(run_id)
        if state["status"] != "running":
            raise RuntimeErrorStateError(
                f"run {run_id} is {state['status']}, not running"
            )
        adapter = ADAPTERS.get(adapter_name)
        if adapter is None:
            raise RuntimeErrorStateError(f"unknown runtime adapter {adapter_name!r}")
        persisted = state["runtime"]
        if persisted.get("adapter") != adapter_name:
            raise RuntimeErrorStateError("runtime adapter mismatch")
        process_info = state["process"]
        return ProcessHandle(
            run_id=run_id,
            pid=process_info["pid"],
            process_start_time=process_info["process_start_time"],
            store=self.store,
            adapter=adapter,
            contract=validate_run_contract(state["contract"]),
            workspace=self.store.run_root(run_id) / "workspace",
        )
