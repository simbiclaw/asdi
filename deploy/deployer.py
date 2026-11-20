"""Blue/green toy-notes deployer with digest-only images and smoke rollback."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.request import ProxyHandler, build_opener

from ci.approval import (
    ApprovalError,
    load_deployment_approval,
    utc_now,
    validate_commit,
    validate_digest,
    validate_ops_registry,
    write_json_atomic,
)
from ci.docker import CliDockerRunner, DockerError, DockerRunner

from .config import DEFAULT_LIMITS_PATH, ProdLimits, load_prod_limits

PROD_NETWORK = "asdi-prod"
CONTAINER_PORT = 8080
SMOKE_PATHS = ("/healthz", "/readyz", "/notes")
FORBIDDEN_RUN_TOKENS = (
    "--privileged",
    "--network=host",
    "--network host",
    "/var/run/docker.sock",
    "--volume",
    "--mount",
    "-v ",
)
SECRET_KEY_TOKENS = ("token", "secret", "password", "api_key", "apikey", "credential")
SmokeFunction = Callable[[int], dict[str, Any]]


class DeployError(RuntimeError):
    """Raised for an invalid deployment request or container command."""


class SmokeError(RuntimeError):
    """Raised when the candidate does not satisfy its smoke checks."""


def _reject_unsafe_run_command(args: Sequence[str]) -> tuple[str, ...]:
    command = tuple(str(arg) for arg in args)
    joined = " ".join(command).lower()
    for token in FORBIDDEN_RUN_TOKENS:
        if token in joined:
            raise DeployError(f"unsafe production run option: {token}")
    for key in SECRET_KEY_TOKENS:
        if key in joined:
            raise DeployError(f"production run command carries a secret-like option: {key}")
    if f"--network {PROD_NETWORK}" not in joined:
        raise DeployError(f"production containers must join only {PROD_NETWORK}")
    return command


def build_run_command(
    *,
    registry: str,
    digest: str,
    commit: str,
    container_name: str,
    port: int,
    run_id: str,
    limits: ProdLimits,
) -> list[str]:
    if not 20000 <= port <= 60999:
        raise DeployError("smoke port must be a run-owned port in 20000-60999")
    image = f"{registry}@{validate_digest(digest)}"
    command = [
        "run",
        "--detach",
        "--name",
        container_name,
        "--network",
        PROD_NETWORK,
        "--publish",
        f"127.0.0.1:{port}:{CONTAINER_PORT}",
        *limits.to_run_args(),
        "--read-only",
        "--tmpfs",
        "/data:rw,size=16m,uid=10001,gid=10001",
        "--env",
        "TOY_NOTES_DB=/data/toy_notes.sqlite3",
        "--label",
        "asdi.zone=prod",
        "--label",
        f"asdi.commit={validate_commit(commit)}",
        "--label",
        f"asdi.digest={digest}",
        "--label",
        f"asdi.run={run_id}",
        image,
    ]
    _reject_unsafe_run_command(command)
    return command


def allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    if not 20000 <= port <= 60999:
        raise DeployError(f"allocated port is outside the run-owned range: {port}")
    return port


def _get_json(port: int, path: str, timeout: float) -> dict[str, Any]:
    opener = build_opener(ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
        if response.status != 200:
            raise SmokeError(f"{path} returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise SmokeError(f"{path} did not return a JSON object")
    return payload


def smoke_http(port: int, *, timeout: float = 2.0) -> dict[str, Any]:
    health = _get_json(port, "/healthz", timeout)
    if health.get("status") != "ok":
        raise SmokeError("/healthz is not ok")
    ready = _get_json(port, "/readyz", timeout)
    if ready.get("status") != "ready":
        raise SmokeError("/readyz is not ready")
    notes = _get_json(port, "/notes", timeout)
    if not isinstance(notes.get("notes"), list):
        raise SmokeError("/notes did not return a notes list")
    return {"healthz": health, "readyz": ready, "notes": {"notes": notes["notes"]}}


def _load_build_record(path: str | Path | None, commit: str, digest: str) -> dict[str, Any] | None:
    if path is None:
        return None
    record_path = Path(path).resolve()
    if not record_path.is_file():
        raise ApprovalError(f"build record is missing: {record_path}")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ApprovalError(f"build record is not valid JSON: {error}") from error
    if not isinstance(record, dict):
        raise ApprovalError("build record must be a JSON object")
    if record.get("schema_version") != "asdi.phase7-build-record/v1":
        raise ApprovalError("build record has an unsupported schema")
    if record.get("commit") != commit:
        raise ApprovalError("build record names a different commit")
    if record.get("digest") != digest:
        raise ApprovalError("build record names a different digest")
    return record


def _load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.is_file():
        return {
            "schema_version": "asdi.phase7-deploy-state/v1",
            "active_slot": None,
            "active_digest": None,
            "active_container": None,
            "active_port": None,
            "history": [],
        }
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != "asdi.phase7-deploy-state/v1":
        raise DeployError(f"unsupported deployment state: {state_path}")
    return state


def deploy(
    *,
    commit: str,
    digest: str,
    decision_file: str | Path,
    registry: str,
    state_dir: str | Path,
    runner: DockerRunner | None = None,
    smoke: SmokeFunction | None = None,
    limits: ProdLimits | None = None,
    build_record_file: str | Path | None = None,
    run_id: str | None = None,
    smoke_attempts: int = 3,
    smoke_delay: float = 0.0,
    max_age_seconds: int | None = None,
    deployed_at: str | None = None,
) -> dict[str, Any]:
    exact_commit = validate_commit(commit)
    exact_digest = validate_digest(digest)
    registry_ref = validate_ops_registry(registry)
    if smoke_attempts < 1:
        raise DeployError("smoke_attempts must be at least one")
    if smoke_delay < 0:
        raise DeployError("smoke_delay cannot be negative")
    approval = load_deployment_approval(
        decision_file, exact_commit, max_age_seconds=max_age_seconds
    )
    build_record = _load_build_record(build_record_file, exact_commit, exact_digest)
    prod_limits = limits or load_prod_limits(DEFAULT_LIMITS_PATH)
    docker = runner or CliDockerRunner()
    smoke_check = smoke or smoke_http

    root = Path(state_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "state.json"
    pointer_path = root / "active.json"
    records_dir = root / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    state = _load_state(state_path)
    previous_digest = state.get("active_digest")
    previous_container = state.get("active_container")
    candidate_slot = "green" if state.get("active_slot") == "blue" else "blue"
    identifier = run_id or f"d-{uuid.uuid4().hex[:12]}"
    container_name = f"toy-notes-{candidate_slot}-{identifier}"
    port = allocate_loopback_port()
    timestamp = deployed_at or utc_now()

    docker.run(["pull", f"{registry_ref}@{exact_digest}"])
    command = build_run_command(
        registry=registry_ref,
        digest=exact_digest,
        commit=exact_commit,
        container_name=container_name,
        port=port,
        run_id=identifier,
        limits=prod_limits,
    )
    run_result = docker.run(command)
    container_id = run_result.stdout.strip().splitlines()[0] if run_result.stdout.strip() else container_name

    smoke_result: dict[str, Any] | None = None
    smoke_error: Exception | None = None
    for attempt in range(1, smoke_attempts + 1):
        try:
            smoke_result = smoke_check(port)
            break
        except Exception as error:  # a failed smoke must never swap the pointer
            smoke_error = error
            if attempt < smoke_attempts:
                time.sleep(smoke_delay)

    if smoke_result is None:
        docker.run(["rm", "--force", container_name], check=False)
        rollback = {
            "performed": True,
            "previous_digest": previous_digest,
            "active_digest_unchanged": True,
            "candidate_container_removed": True,
            "reason": str(smoke_error or "smoke failed"),
        }
        state.setdefault("history", []).append(
            {
                "event": "rollback",
                "at": timestamp,
                "commit": exact_commit,
                "candidate_digest": exact_digest,
                "rollback": rollback,
            }
        )
        write_json_atomic(state_path, state)
        record = {
            "schema_version": "asdi.phase7-deploy-record/v1",
            "status": "rolled_back",
            "commit": exact_commit,
            "candidate_digest": exact_digest,
            "active_digest": previous_digest,
            "registry": registry_ref,
            "network": PROD_NETWORK,
            "smoke_paths": list(SMOKE_PATHS),
            "approval": approval,
            "build_record": build_record,
            "rollback": rollback,
            "run_id": identifier,
            "recorded_at": timestamp,
        }
        record_path = write_json_atomic(records_dir / f"{identifier}.json", record)
        record["record_path"] = str(record_path)
        write_json_atomic(record_path, record)
        return record

    pointer = {
        "schema_version": "asdi.phase7-active-pointer/v1",
        "slot": candidate_slot,
        "commit": exact_commit,
        "digest": exact_digest,
        "container_name": container_name,
        "container_id": container_id,
        "smoke_port": port,
        "updated_at": timestamp,
    }
    write_json_atomic(pointer_path, pointer)
    state.update(
        {
            "active_slot": candidate_slot,
            "active_digest": exact_digest,
            "active_container": container_name,
            "active_port": port,
        }
    )
    state.setdefault("history", []).append(
        {
            "event": "swap",
            "at": timestamp,
            "commit": exact_commit,
            "digest": exact_digest,
            "previous_digest": previous_digest,
        }
    )
    write_json_atomic(state_path, state)

    retired_container_removal = None
    if previous_container and previous_container != container_name:
        removed = docker.run(["rm", "--force", previous_container], check=False)
        retired_container_removal = {"container": previous_container, "returncode": removed.returncode}

    record = {
        "schema_version": "asdi.phase7-deploy-record/v1",
        "status": "deployed",
        "commit": exact_commit,
        "digest": exact_digest,
        "previous_digest": previous_digest,
        "active_pointer": str(pointer_path),
        "registry": registry_ref,
        "network": PROD_NETWORK,
        "container_name": container_name,
        "container_id": container_id,
        "smoke_port": port,
        "smoke_paths": list(SMOKE_PATHS),
        "smoke_result": smoke_result,
        "approval": approval,
        "build_record": build_record,
        "retired_container_removal": retired_container_removal,
        "run_id": identifier,
        "recorded_at": timestamp,
    }
    record_path = write_json_atomic(records_dir / f"{identifier}.json", record)
    record["record_path"] = str(record_path)
    write_json_atomic(record_path, record)
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asdi-phase7-deploy")
    parser.add_argument("--commit", required=True, help="exact 40-character main commit")
    parser.add_argument("--digest", required=True, help="sha256 image digest from the build record")
    parser.add_argument("--decision-file", required=True, help="durable passing deployment decision")
    parser.add_argument("--build-record", default=None, help="optional matching CI build record")
    parser.add_argument("--registry", required=True, help="ops registry repository reference")
    parser.add_argument("--state-dir", required=True, help="run-owned deploy state directory")
    parser.add_argument("--limits", default=str(DEFAULT_LIMITS_PATH))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--smoke-attempts", type=int, default=3)
    parser.add_argument("--smoke-delay", type=float, default=0.0)
    parser.add_argument("--max-age-seconds", type=int, default=None)
    parser.add_argument("--docker", default="docker", help="Docker CLI executable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        record = deploy(
            commit=arguments.commit,
            digest=arguments.digest,
            decision_file=arguments.decision_file,
            registry=arguments.registry,
            state_dir=arguments.state_dir,
            runner=CliDockerRunner(arguments.docker),
            limits=load_prod_limits(arguments.limits),
            build_record_file=arguments.build_record,
            run_id=arguments.run_id,
            smoke_attempts=arguments.smoke_attempts,
            smoke_delay=arguments.smoke_delay,
            max_age_seconds=arguments.max_age_seconds,
        )
    except (ApprovalError, DeployError, DockerError, OSError, ValueError) as error:
        print(f"deploy refused: {error}", file=sys.stderr)
        return 2
    if record["status"] == "rolled_back":
        print(f"smoke failed; rolled back: {record['record_path']}")
        return 3
    print(
        f"deployed commit={record['commit']} digest={record['digest']} "
        f"pointer={record['active_pointer']} record={record['record_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
