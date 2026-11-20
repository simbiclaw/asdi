from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


RUN_ID_PATTERN = re.compile(r"^r-[A-Za-z0-9-]+$")
SOURCE_PREFIX = "src/toy_notes/"
DEFECT_ENV = "TOY_NOTES_INJECT_DEFECT"
DEFECT_CREATE = "create"
UI_ENV = "NOTES_UI_ENABLED"
STATUS_VALUES = {"pass", "fail", "blocked", "error", "not_applicable"}
CONTROL_VALUES = {"caught", "missed", "not_applicable"}
FIXTURES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "proof-values.json").read_text()
)


@dataclass
class ServerHandle:
    process: subprocess.Popen[bytes]
    port: int
    base_url: str
    db_path: Path
    stdout_path: Path
    stderr_path: Path


@dataclass
class ProofResult:
    status: str
    evidence: list[str]
    observed: dict[str, Any]


@dataclass
class ControlResult:
    value: str
    evidence: list[str]
    observed: dict[str, Any]


def harness_root() -> Path:
    return Path(__file__).resolve().parents[2]


def head_root() -> Path:
    configured = os.environ.get("ASDI_HEAD")
    if configured and Path(configured).is_dir():
        return Path(configured).resolve()
    current = Path.cwd().resolve()
    if (current / "verify" / "bin" / "verify").is_file():
        return current
    return harness_root()


def evidence_dir(root: Path) -> Path:
    configured = os.environ.get("ASDI_EVIDENCE_DIR")
    if configured:
        return Path(configured).resolve()
    identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"asdi-toy-notes-{identity}"


def current_run_id(state: dict[str, Any] | None = None) -> str:
    if state and isinstance(state.get("run_id"), str) and RUN_ID_PATTERN.match(state["run_id"]):
        return state["run_id"]
    configured = os.environ.get("ASDI_RUN_ID", "")
    if configured and RUN_ID_PATTERN.match(configured):
        return configured
    return "r-" + uuid.uuid4().hex


def current_commit(root: Path) -> str:
    configured = os.environ.get("ASDI_COMMIT")
    if configured:
        return configured
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else "unknown"


def load_features(root: Path | None = None) -> dict[str, dict[str, Any]]:
    feature_root = (root or harness_root()) / "verify" / "features"
    features: dict[str, dict[str, Any]] = {}
    for path in sorted(feature_root.glob("*.md")):
        match = re.match(r"\A---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
        if match is None:
            raise ValueError(f"feature file has no front matter: {path}")
        front_matter = json.loads(match.group(1))
        for key in ("id", "title", "paths", "class_floor", "drive", "proof", "negative_control", "limits"):
            if key not in front_matter:
                raise ValueError(f"feature {path.name} is missing {key}")
        if not front_matter["limits"]:
            raise ValueError(f"feature {front_matter['id']} has empty limits")
        if front_matter["negative_control"].get("expect") != "fail":
            raise ValueError(f"feature {front_matter['id']} has no failing negative control")
        features[front_matter["id"]] = front_matter
    if not features:
        raise ValueError("no feature files found")
    return features


def product_sources(root: Path) -> list[str]:
    source_root = root / "src" / "toy_notes"
    if not source_root.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in source_root.rglob("*.py")
    )


def uncovered_sources(features: dict[str, dict[str, Any]], root: Path) -> list[str]:
    patterns = [pattern for feature in features.values() for pattern in feature["paths"]]
    return [
        path
        for path in product_sources(root)
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
    ]


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path) -> dict[str, str]:
    skipped = {".git", "__pycache__", ".asdi-evidence"}
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in skipped for part in relative.parts) or path.suffix == ".pyc":
            continue
        result[relative.as_posix()] = _file_digest(path)
    return result


def changed_source_paths(base: Path, head: Path) -> list[str]:
    baseline = _tree_digest(base.resolve())
    candidate = _tree_digest(head.resolve())
    changed = []
    for name in sorted(set(baseline) | set(candidate)):
        if name.startswith(SOURCE_PREFIX) and baseline.get(name) != candidate.get(name):
            changed.append(name)
    return changed


def features_for_changed(
    spec: str, features: dict[str, dict[str, Any]]
) -> list[str]:
    left, separator, right = spec.partition("..")
    if not separator or not left or not right:
        raise ValueError("--changed requires <base>..<head> filesystem roots")
    paths = changed_source_paths(Path(left), Path(right))
    mapped: set[str] = set()
    uncovered: list[str] = []
    for path in paths:
        matches = [
            feature_id
            for feature_id, feature in features.items()
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in feature["paths"])
        ]
        if not matches:
            uncovered.append(path)
        mapped.update(matches)
    if uncovered:
        raise ValueError(f"changed source paths have no feature: {', '.join(uncovered)}")
    if not mapped:
        raise ValueError("no feature maps to the changed source paths")
    return sorted(mapped)


def features_for_environment(features: dict[str, dict[str, Any]]) -> list[str]:
    base = os.environ.get("ASDI_BASE")
    head = os.environ.get("ASDI_HEAD")
    if not base or not head or Path(base).resolve() == Path(head).resolve():
        return sorted(features)
    try:
        selected = features_for_changed(f"{base}..{head}", features)
    except (OSError, ValueError):
        return sorted(features)
    return selected


def _environment(root: Path, *, defect: bool = False, ui: bool = False) -> dict[str, str]:
    environment = os.environ.copy()
    python_path = str(root / "src")
    if environment.get("PYTHONPATH"):
        python_path = python_path + os.pathsep + environment["PYTHONPATH"]
    environment["PYTHONPATH"] = python_path
    environment[UI_ENV] = "1" if ui else "0"
    if defect:
        environment[DEFECT_ENV] = DEFECT_CREATE
    else:
        environment.pop(DEFECT_ENV, None)
    return environment


def run_cli(
    root: Path,
    *arguments: str,
    defect: bool = False,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "toy_notes.cli", *arguments]
    return subprocess.run(
        command,
        cwd=root,
        env=_environment(root, defect=defect),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _http(
    method: str,
    base_url: str,
    path: str,
    *,
    payload: dict[str, str] | None = None,
    form: bool = False,
    timeout: float = 5.0,
) -> dict[str, Any]:
    data: bytes | None = None
    headers: dict[str, str] = {}
    if payload is not None:
        if form:
            data = urllib.parse.urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {
                "status": int(response.status),
                "body": response.read().decode("utf-8", "replace"),
            }
    except urllib.error.HTTPError as error:
        return {
            "status": int(error.code),
            "body": error.read().decode("utf-8", "replace"),
        }
    except urllib.error.URLError as error:
        return {"status": 0, "body": f"transport error: {error}"}


def _http_json(response: dict[str, Any]) -> Any:
    return json.loads(response["body"])


def _safe_json(text: str, default: Any) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _count_rows(db_path: Path) -> int:
    if not db_path.is_file():
        return 0
    with sqlite3.connect(str(db_path)) as connection:
        try:
            return int(connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0])
        except sqlite3.OperationalError:
            return 0


def _seed_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notes ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "title TEXT NOT NULL, "
            "body TEXT NOT NULL, "
            "created_at TEXT NOT NULL)"
        )
        connection.execute("DELETE FROM notes")
        connection.execute(
            "INSERT INTO notes (id, title, body, created_at) VALUES (1, ?, ?, ?)",
            (FIXTURES["ui_seed_title"], "synthetic", FIXTURES["fixed_created_at"]),
        )


def start_server(
    root: Path,
    db_path: Path,
    evidence: Path,
    *,
    label: str,
    ui: bool = False,
    defect: bool = False,
) -> ServerHandle:
    run_directory = evidence / "run"
    run_directory.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    port_file = run_directory / f"{label}.port"
    stdout_path = run_directory / f"{label}.stdout.log"
    stderr_path = run_directory / f"{label}.stderr.log"
    port_file.unlink(missing_ok=True)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "toy_notes.server",
                "--db",
                str(db_path),
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--port-file",
                str(port_file),
            ],
            cwd=root,
            env=_environment(root, defect=defect, ui=ui),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    try:
        port = _wait_for_port(port_file, process)
    except BaseException:
        _stop_process(process)
        raise
    return ServerHandle(process, port, f"http://127.0.0.1:{port}", db_path, stdout_path, stderr_path)


def _wait_for_port(port_file: Path, process: subprocess.Popen[bytes], timeout: float = 15.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited before binding: {process.returncode}")
        if port_file.is_file():
            value = port_file.read_text(encoding="utf-8").strip()
            if value.isdigit():
                port = int(value)
                response = _http("GET", f"http://127.0.0.1:{port}", "/healthz", timeout=1.0)
                if response["status"] == 200:
                    return port
        time.sleep(0.05)
    raise RuntimeError("server did not become healthy before timeout")


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def _stop_pid(pid: int) -> bool:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    return True


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def stop_server(server: ServerHandle) -> None:
    _stop_process(server.process)


def state_path(evidence: Path) -> Path:
    return evidence / "run" / "launch.json"


def load_state(evidence: Path) -> dict[str, Any] | None:
    path = state_path(evidence)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_evidence(evidence: Path, relative: str, content: str) -> str:
    path = evidence / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path.relative_to(evidence).as_posix()


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _record_command(evidence: Path, directory: str, name: str, command: subprocess.CompletedProcess[str]) -> list[str]:
    return [
        _write_evidence(evidence, f"{directory}/{name}.stdout.txt", command.stdout),
        _write_evidence(evidence, f"{directory}/{name}.stderr.txt", command.stderr),
    ]


def launch_main() -> int:
    root = head_root()
    evidence = evidence_dir(root)
    evidence.mkdir(parents=True, exist_ok=True)
    path = state_path(evidence)
    state = load_state(evidence)
    if state and state.get("head_root") == str(root) and _alive(int(state.get("pid", 0) or 0)):
        probe = _http("GET", str(state.get("base_url", "")), "/healthz", timeout=2.0)
        if probe["status"] == 200:
            print(_json_text({"status": "pass", "launch": "reused", "port": state.get("port")}), end="")
            return 0
        _stop_pid(int(state.get("pid", 0)))
    try:
        server = start_server(
            root,
            evidence / "run" / "toy-notes.sqlite3",
            evidence,
            label="main",
            ui=True,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(_json_text({"status": "blocked", "error": str(error)}), end="")
        return 2
    state = {
        "pid": server.process.pid,
        "port": server.port,
        "base_url": server.base_url,
        "db": str(server.db_path),
        "run_id": current_run_id(),
        "head_root": str(root),
        "harness_root": str(harness_root()),
        "evidence_dir": str(evidence),
        "ui_enabled": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_text(state), encoding="utf-8")
    print(_json_text({"status": "pass", "launch": "started", "port": server.port, "evidence": str(evidence)}), end="")
    return 0


def doctor_main() -> int:
    root = head_root()
    evidence = evidence_dir(root)
    state = load_state(evidence)
    checks: dict[str, bool] = {}
    if state is None:
        print(_json_text({"status": "blocked", "checks": {"launch_state": False}}), end="")
        return 2
    try:
        features = load_features()
        checks["feature_map"] = not uncovered_sources(features, root)
        checks["process"] = _alive(int(state.get("pid", 0)))
        health = _http("GET", str(state.get("base_url", "")), "/healthz", timeout=2.0)
        ready = _http("GET", str(state.get("base_url", "")), "/readyz", timeout=2.0)
        checks["healthz"] = health["status"] == 200 and _http_json(health)["status"] == "ok"
        checks["readyz"] = ready["status"] == 200 and _http_json(ready)["status"] == "ready"
        checks["database"] = Path(str(state.get("db", ""))).is_file()
    except (KeyError, OSError, ValueError, TypeError) as error:
        checks["inspection"] = False
        print(_json_text({"status": "blocked", "checks": checks, "error": str(error)}), end="")
        return 2
    status = "pass" if all(checks.values()) else "blocked"
    print(_json_text({"status": status, "checks": checks}), end="")
    return 0 if status == "pass" else 2


def drive_cli(feature: dict[str, Any], state: dict[str, Any], evidence: Path, run_id: str) -> ProofResult:
    root = head_root()
    directory = f"{feature['id']}/{run_id}"
    db_path = evidence / directory / "cli.sqlite3"
    export_path = evidence / directory / "export.json"
    evidence_files: list[str] = []
    observed: dict[str, Any] = {"commands": []}
    try:
        commands: dict[str, subprocess.CompletedProcess[str]] = {}
        commands["create"] = run_cli(
            root,
            "--db", str(db_path),
            "create",
            "--title", FIXTURES["cli_title"],
            "--body", "synthetic",
        )
        commands["list"] = run_cli(root, "--db", str(db_path), "list")
        commands["read"] = run_cli(root, "--db", str(db_path), "read", "--id", "1")
        commands["export"] = run_cli(root, "--db", str(db_path), "export", "--out", str(export_path))
        for name, command in commands.items():
            evidence_files.extend(_record_command(evidence, directory, name, command))
            observed["commands"].append({"name": name, "exit_code": command.returncode})
        rows = _count_rows(db_path)
        exported = (
            _safe_json(export_path.read_text(encoding="utf-8"), [])
            if export_path.is_file()
            else []
        )
        create_payload = _safe_json(commands["create"].stdout, {})
        list_payload = _safe_json(commands["list"].stdout, [])
        read_payload = _safe_json(commands["read"].stdout, {})
        observed["row_count"] = rows
        observed["exported"] = exported
        observed["expected_title"] = FIXTURES["cli_title"]
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
        checks = {
            "all_commands_zero": all(command.returncode == 0 for command in commands.values()),
            "one_stored_row": rows == 1,
            "create_json": isinstance(create_payload, dict)
            and create_payload.get("title") == FIXTURES["cli_title"],
            "list_json": isinstance(list_payload, list)
            and any(isinstance(note, dict) and note.get("title") == FIXTURES["cli_title"] for note in list_payload),
            "read_json": isinstance(read_payload, dict) and read_payload.get("id") == 1,
            "export_json": any(
                isinstance(note, dict) and note.get("title") == FIXTURES["cli_title"]
                for note in exported
            ),
            "proof_contains": str(feature["proof"].get("contains", "")) in commands["list"].stdout,
        }
        status = "pass" if all(checks.values()) else "fail"
        observed["checks"] = checks
    except Exception as error:
        status = "error"
        observed["error"] = str(error)
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
    return ProofResult(status, evidence_files, observed)


def drive_http(feature: dict[str, Any], state: dict[str, Any], evidence: Path, run_id: str) -> ProofResult:
    directory = f"{feature['id']}/{run_id}"
    evidence_files: list[str] = []
    observed: dict[str, Any] = {}
    try:
        base_url = str(state["base_url"])
        db_path = Path(str(state["db"]))
        before = _count_rows(db_path)
        responses = {
            "healthz": _http("GET", base_url, "/healthz"),
            "readyz": _http("GET", base_url, "/readyz"),
            "metrics": _http("GET", base_url, "/metrics"),
            "notes_before": _http("GET", base_url, "/notes"),
            "create": _http(
                "POST",
                base_url,
                "/notes",
                payload={"title": FIXTURES["http_title"], "body": "synthetic"},
            ),
            "notes_after": _http("GET", base_url, "/notes"),
        }
        for name, response in responses.items():
            evidence_files.append(_write_evidence(evidence, f"{directory}/{name}.txt", response["body"]))
        after = _count_rows(db_path)
        notes_payload = _safe_json(responses["notes_after"]["body"], {})
        notes_after = notes_payload.get("notes", []) if isinstance(notes_payload, dict) else []
        health_payload = _safe_json(responses["healthz"]["body"], {})
        ready_payload = _safe_json(responses["readyz"]["body"], {})
        health_ok = isinstance(health_payload, dict) and health_payload.get("status") == "ok"
        ready_ok = isinstance(ready_payload, dict) and ready_payload.get("status") == "ready"
        observed = {
            "statuses": {name: response["status"] for name, response in responses.items()},
            "row_count_before": before,
            "row_count_after": after,
            "titles": [note.get("title") for note in notes_after if isinstance(note, dict)],
        }
        checks = {
            "healthz": responses["healthz"]["status"] == 200 and health_ok,
            "readyz": responses["readyz"]["status"] == 200 and ready_ok,
            "metrics": responses["metrics"]["status"] == 200
            and "toy_notes_requests_total" in responses["metrics"]["body"],
            "create_201": responses["create"]["status"] == 201,
            "one_new_row": after == before + 1,
            "proof_title": FIXTURES["http_title"] in observed["titles"],
        }
        observed["checks"] = checks
        status = "pass" if all(checks.values()) else "fail"
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
    except Exception as error:
        status = "error"
        observed = {"error": str(error)}
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
    return ProofResult(status, evidence_files, observed)


def drive_ui(feature: dict[str, Any], state: dict[str, Any], evidence: Path, run_id: str) -> ProofResult:
    root = head_root()
    directory = f"{feature['id']}/{run_id}"
    evidence_files: list[str] = []
    observed: dict[str, Any] = {}
    off_db = evidence / directory / "off.sqlite3"
    on_db = evidence / directory / "on.sqlite3"
    _seed_db(off_db)
    _seed_db(on_db)
    off: ServerHandle | None = None
    on: ServerHandle | None = None
    try:
        off = start_server(root, off_db, evidence, label=f"ui-off-{run_id}", ui=False)
        on = start_server(root, on_db, evidence, label=f"ui-on-{run_id}", ui=True)
        responses = {
            "ui_off": _http("GET", off.base_url, "/notes/ui"),
            "ui_on": _http("GET", on.base_url, "/notes/ui"),
            "health_off": _http("GET", off.base_url, "/healthz"),
            "health_on": _http("GET", on.base_url, "/healthz"),
            "notes_off": _http("GET", off.base_url, "/notes"),
            "notes_on": _http("GET", on.base_url, "/notes"),
            "submit": _http(
                "POST",
                on.base_url,
                "/notes",
                payload={"title": FIXTURES["ui_title"], "body": "synthetic"},
                form=True,
            ),
            "ui_after": _http("GET", on.base_url, "/notes/ui"),
        }
        for name, response in responses.items():
            evidence_files.append(_write_evidence(evidence, f"{directory}/{name}.txt", response["body"]))
        after = _count_rows(on_db)
        observed = {
            "statuses": {name: response["status"] for name, response in responses.items()},
            "row_count_after": after,
            "flag_off_body": responses["ui_off"]["body"],
            "flag_on_contains_form": FIXTURES["form_marker"] in responses["ui_on"]["body"],
            "non_ui_health_equal": responses["health_off"]["body"] == responses["health_on"]["body"],
            "non_ui_notes_equal": responses["notes_off"]["body"] == responses["notes_on"]["body"],
        }
        checks = {
            "default_off_404": responses["ui_off"]["status"] == 404
            and "ui_disabled" in responses["ui_off"]["body"],
            "enabled_200": responses["ui_on"]["status"] == 200
            and _http_json(responses["health_on"])["status"] == "ok",
            "html_form": FIXTURES["form_marker"] in responses["ui_on"]["body"]
            and FIXTURES["ui_seed_title"] in responses["ui_on"]["body"],
            "flag_changes_only_ui": observed["non_ui_health_equal"] and observed["non_ui_notes_equal"],
            "form_created_row": responses["submit"]["status"] == 201 and after == 2,
            "ui_lists_new_note": FIXTURES["ui_title"] in responses["ui_after"]["body"],
        }
        observed["checks"] = checks
        status = "pass" if all(checks.values()) else "fail"
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
    except Exception as error:
        status = "error"
        observed = {"error": str(error)}
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
    finally:
        if on is not None:
            stop_server(on)
        if off is not None:
            stop_server(off)
    return ProofResult(status, evidence_files, observed)


DRIVERS = {
    "cli-notes": drive_cli,
    "http-notes": drive_http,
    "ui-note-list": drive_ui,
}


def drive_feature(feature: dict[str, Any], state: dict[str, Any], evidence: Path, run_id: str) -> ProofResult:
    driver = DRIVERS.get(feature["id"])
    if driver is None:
        return ProofResult("blocked", [], {"error": f"no driver for {feature['id']}"})
    return driver(feature, state, evidence, run_id)


def control_cli(feature: dict[str, Any], evidence: Path, run_id: str) -> ControlResult:
    root = head_root()
    directory = f"controls/{feature['id']}/{run_id}"
    db_path = evidence / directory / "control.sqlite3"
    observed: dict[str, Any] = {}
    evidence_files: list[str] = []
    try:
        command = run_cli(
            root,
            "--db", str(db_path),
            "create",
            "--title", FIXTURES["control_title"],
            defect=True,
        )
        evidence_files.extend(_record_command(evidence, directory, "create", command))
        rows = _count_rows(db_path)
        observed = {
            "exit_code": command.returncode,
            "stderr": command.stderr,
            "row_count": rows,
        }
        checks = {
            "create_failed": command.returncode != 0,
            "no_row": rows == 0,
        }
        observed["checks"] = checks
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
        return ControlResult("caught" if all(checks.values()) else "missed", evidence_files, observed)
    except Exception as error:
        observed = {"error": str(error)}
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
        return ControlResult("missed", evidence_files, observed)


def control_http(feature: dict[str, Any], evidence: Path, run_id: str) -> ControlResult:
    root = head_root()
    directory = f"controls/{feature['id']}/{run_id}"
    db_path = evidence / directory / "control.sqlite3"
    server: ServerHandle | None = None
    evidence_files: list[str] = []
    observed: dict[str, Any] = {}
    try:
        server = start_server(
            root,
            db_path,
            evidence,
            label=f"control-http-{run_id}",
            ui=False,
            defect=True,
        )
        response = _http(
            "POST",
            server.base_url,
            "/notes",
            payload={"title": FIXTURES["control_title"], "body": "synthetic"},
        )
        evidence_files.append(_write_evidence(evidence, f"{directory}/create.txt", response["body"]))
        rows = _count_rows(db_path)
        observed = {"status": response["status"], "body": response["body"], "row_count": rows}
        checks = {
            "create_rejected": response["status"] != 201,
            "no_row": rows == 0,
        }
        observed["checks"] = checks
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
        return ControlResult("caught" if all(checks.values()) else "missed", evidence_files, observed)
    except Exception as error:
        observed = {"error": str(error)}
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
        return ControlResult("missed", evidence_files, observed)
    finally:
        if server is not None:
            stop_server(server)


def control_ui(feature: dict[str, Any], evidence: Path, run_id: str) -> ControlResult:
    root = head_root()
    directory = f"controls/{feature['id']}/{run_id}"
    db_path = evidence / directory / "control.sqlite3"
    _seed_db(db_path)
    server: ServerHandle | None = None
    evidence_files: list[str] = []
    observed: dict[str, Any] = {}
    try:
        server = start_server(
            root,
            db_path,
            evidence,
            label=f"control-ui-{run_id}",
            ui=True,
            defect=True,
        )
        before = _http("GET", server.base_url, "/notes/ui")
        submit = _http(
            "POST",
            server.base_url,
            "/notes",
            payload={"title": FIXTURES["control_title"], "body": "synthetic"},
            form=True,
        )
        after = _http("GET", server.base_url, "/notes/ui")
        for name, response in {"before": before, "submit": submit, "after": after}.items():
            evidence_files.append(_write_evidence(evidence, f"{directory}/{name}.txt", response["body"]))
        rows = _count_rows(db_path)
        observed = {
            "statuses": {"before": before["status"], "submit": submit["status"], "after": after["status"]},
            "row_count": rows,
        }
        checks = {
            "create_rejected": submit["status"] != 201,
            "control_absent": FIXTURES["control_title"] not in after["body"],
            "no_new_row": rows == 1,
        }
        observed["checks"] = checks
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
        return ControlResult("caught" if all(checks.values()) else "missed", evidence_files, observed)
    except Exception as error:
        observed = {"error": str(error)}
        evidence_files.append(_write_evidence(evidence, f"{directory}/observed.json", _json_text(observed)))
        return ControlResult("missed", evidence_files, observed)
    finally:
        if server is not None:
            stop_server(server)


CONTROLS = {
    "cli-notes": control_cli,
    "http-notes": control_http,
    "ui-note-list": control_ui,
}


def run_control(feature: dict[str, Any], evidence: Path, run_id: str) -> ControlResult:
    control = CONTROLS.get(feature["id"])
    if control is None:
        return ControlResult("missed", [], {"error": f"no control for {feature['id']}"})
    return control(feature, evidence, run_id)


def _select_features(arguments: argparse.Namespace, features: dict[str, dict[str, Any]]) -> list[str]:
    if getattr(arguments, "changed", None):
        return features_for_changed(arguments.changed, features)
    if arguments.ids:
        unknown = [feature_id for feature_id in arguments.ids if feature_id not in features]
        if unknown:
            raise ValueError(f"unknown feature ids: {', '.join(unknown)}")
        return list(arguments.ids)
    return sorted(features)


def drive_main(arguments: argparse.Namespace) -> int:
    root = head_root()
    evidence = evidence_dir(root)
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        features = load_features()
        selected = _select_features(arguments, features)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(_json_text({"status": "blocked", "error": str(error)}), end="")
        return 2
    state = load_state(evidence)
    run_id = current_run_id(state)
    result_features: list[dict[str, Any]] = []
    statuses: list[str] = []
    controls: list[str] = []
    if state is None:
        for feature_id in selected:
            reason = _write_evidence(
                evidence,
                f"errors/{feature_id}-{run_id}.txt",
                "verify launch state is missing or invalid",
            )
            result_features.append(
                {
                    "id": feature_id,
                    "status": "blocked",
                    "control": "missed",
                    "evidence": [reason],
                    "limits": list(features[feature_id]["limits"]),
                }
            )
            statuses.append("blocked")
            controls.append("missed")
    else:
        for feature_id in selected:
            feature = features[feature_id]
            proof = drive_feature(feature, state, evidence, run_id)
            control = run_control(feature, evidence, run_id)
            if proof.status not in STATUS_VALUES or control.value not in CONTROL_VALUES:
                proof.status = "error"
                control.value = "missed"
            result_features.append(
                {
                    "id": feature_id,
                    "status": proof.status,
                    "control": control.value,
                    "evidence": proof.evidence + control.evidence,
                    "limits": list(feature["limits"]),
                }
            )
            statuses.append(proof.status)
            controls.append(control.value)
    result = {
        "schema": 2,
        "run_id": run_id,
        "commit": current_commit(root),
        "features": result_features,
    }
    (evidence / "result.json").write_text(_json_text(result), encoding="utf-8")
    print(
        _json_text(
            {
                "status": "pass" if all(value == "pass" for value in statuses) else "fail",
                "features": dict(zip(selected, statuses)),
                "controls": dict(zip(selected, controls)),
                "result": str(evidence / "result.json"),
            }
        ),
        end="",
    )
    if any(value in {"blocked", "error"} for value in statuses):
        return 2
    if any(value == "fail" for value in statuses) or any(value != "caught" for value in controls):
        return 1
    return 0


def control_main(arguments: argparse.Namespace) -> int:
    root = head_root()
    evidence = evidence_dir(root)
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        features = load_features()
        selected = _select_features(arguments, features)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(_json_text({"status": "blocked", "error": str(error)}), end="")
        return 2
    run_id = current_run_id(load_state(evidence))
    observed: dict[str, str] = {}
    for feature_id in selected:
        observed[feature_id] = run_control(features[feature_id], evidence, run_id).value
    print(_json_text({"controls": observed}), end="")
    return 0 if all(value == "caught" for value in observed.values()) else 1


def cleanup_main() -> int:
    evidence = evidence_dir(head_root())
    state = load_state(evidence)
    stopped = False
    if state:
        stopped = _stop_pid(int(state.get("pid", 0)))
    print(_json_text({"status": "pass", "stopped": stopped, "evidence_preserved": str(evidence)}), end="")
    return 0


def full_main(arguments: argparse.Namespace) -> int:
    selected = features_for_environment(load_features())
    exit_code = launch_main()
    try:
        if exit_code == 0:
            exit_code = doctor_main()
        if exit_code == 0:
            exit_code = drive_main(SimpleNamespace(ids=selected, changed=None))
        if exit_code == 0:
            exit_code = control_main(SimpleNamespace(ids=selected, changed=None))
    finally:
        cleanup_main()
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("launch")
    commands.add_parser("doctor")
    drive = commands.add_parser("drive")
    drive.add_argument("ids", nargs="*")
    drive.add_argument("--changed")
    control = commands.add_parser("control")
    control.add_argument("ids", nargs="*")
    commands.add_parser("cleanup")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command is None:
            return full_main(arguments)
        if arguments.command == "launch":
            return launch_main()
        if arguments.command == "doctor":
            return doctor_main()
        if arguments.command == "drive":
            return drive_main(arguments)
        if arguments.command == "control":
            return control_main(arguments)
        if arguments.command == "cleanup":
            return cleanup_main()
        raise ValueError(f"unknown command: {arguments.command}")
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(_json_text({"status": "error", "error": str(error)}), end="", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
