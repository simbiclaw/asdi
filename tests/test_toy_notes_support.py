from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ROOT = ROOT / "pilots" / "toy_notes"
SCHEMAS = ROOT / "schemas"
VERIFY = PRODUCT_ROOT / "verify" / "bin" / "verify"
SELF_TEST = PRODUCT_ROOT / "verify" / "self_test.py"


def product_environment(root: Path = PRODUCT_ROOT, *, ui: bool = False, defect: bool = False) -> dict[str, str]:
    environment = os.environ.copy()
    python_path = str(root / "src")
    if environment.get("PYTHONPATH"):
        python_path = python_path + os.pathsep + environment["PYTHONPATH"]
    environment["PYTHONPATH"] = python_path
    environment["NOTES_UI_ENABLED"] = "1" if ui else "0"
    if defect:
        environment["TOY_NOTES_INJECT_DEFECT"] = "create"
    else:
        environment.pop("TOY_NOTES_INJECT_DEFECT", None)
    return environment


def run_cli(root: Path, db_path: Path, *arguments: str, defect: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "toy_notes.cli", "--db", str(db_path), *arguments],
        cwd=root,
        env=product_environment(root, defect=defect),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def http_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
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
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"status": int(response.status), "body": response.read().decode("utf-8", "replace")}
    except urllib.error.HTTPError as error:
        return {"status": int(error.code), "body": error.read().decode("utf-8", "replace")}


@dataclass
class ProductServer:
    process: subprocess.Popen[bytes]
    port: int
    base_url: str
    db_path: Path

    def request(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return http_request(self.base_url, path, **kwargs)

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=5)


def launch_product(
    db_path: Path,
    run_directory: Path,
    *,
    root: Path = PRODUCT_ROOT,
    ui: bool = False,
    defect: bool = False,
) -> ProductServer:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_directory.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex[:10]
    port_file = run_directory / f"port-{suffix}.txt"
    stdout_path = run_directory / f"server-{suffix}.stdout.log"
    stderr_path = run_directory / f"server-{suffix}.stderr.log"
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
            env=product_environment(root, ui=ui, defect=defect),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    deadline = time.monotonic() + 15
    port = 0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"product server exited: {process.returncode}")
        if port_file.is_file() and port_file.read_text(encoding="utf-8").strip().isdigit():
            port = int(port_file.read_text(encoding="utf-8").strip())
            response = http_request(f"http://127.0.0.1:{port}", "/healthz", timeout=1.0)
            if response["status"] == 200:
                break
        time.sleep(0.05)
    if port == 0:
        process.terminate()
        raise AssertionError("product server did not bind a run-owned port")
    return ProductServer(process, port, f"http://127.0.0.1:{port}", db_path)


def row_count(db_path: Path) -> int:
    if not db_path.is_file():
        return 0
    with sqlite3.connect(str(db_path)) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0])


def seed_note(db_path: Path, title: str = "seed", created_at: str = "2026-11-20T00:00:00+00:00") -> None:
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
            (title, "synthetic", created_at),
        )


def run_process(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
