#!/usr/bin/env python3
"""Explicit Codex CLI adapter for the local ASDI lifecycle.

This adapter is opt-in.  It runs Codex non-interactively in workspace-write
mode with approvals disabled and validates that the requested artifacts exist.
It does not authorize production access, remote merge, or irreversible actions.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import tempfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
import urllib.error


PROMPT_TEMPLATE = """You are implementing one bounded ASDI lifecycle task.

Mission ID: {mission_id}
Variant: {variant}
Objective: {objective}

Create exactly these files in the current workspace:
1. app.py — a Python 3 CLI with --self-check and --handle.
2. manifest.json — JSON with mission_id, variant, revision, paths, fixture_agent=false.

Behavior requirements:
- --self-check must exit 0 and print JSON with ok=true.
- --handle --scenario normal --flag-enabled false must exit 0 and print JSON with ok=true.
- --flag-enabled is a value argument and must accept exactly "true" or "false"; it must not be a store_true flag.
- For variant "buggy", --handle --scenario load --flag-enabled true must intentionally return ok=false and exit 1.
- For variants "good" and "repair", --handle --scenario load --flag-enabled true must return ok=true and exit 0.
- Do not use secrets, subprocess, sockets, eval, or exec.
- Do not run git commands, modify outside the workspace, or perform irreversible actions.
- Keep the implementation small and deterministic.

Finish only when both files exist and the applicable checks pass.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument(
        "--variant",
        choices=("good", "buggy", "repair"),
        required=True,
    )
    parser.add_argument(
        "--codex-path",
        default=shutil.which("codex"),
        help="Absolute Codex CLI path; defaults to PATH discovery.",
    )
    parser.add_argument(
        "--codex-home",
        default="/Users/russell/.codex",
        help="Explicit CODEX_HOME for the nested Codex process.",
    )
    parser.add_argument(
        "--isolate-codex-home",
        action="store_true",
        help="Copy provider configuration into a temporary CODEX_HOME without parent thread state.",
    )
    parser.add_argument(
        "--proxy",
        default="http://127.0.0.1:7890",
        help="Optional proxy for provider access.",
    )
    parser.add_argument(
        "--model",
        default="qwen3.6-35b-dspark-local",
        help="LiteLLM model identifier.",
    )
    parser.add_argument(
        "--model-provider",
        default="litellm",
        help="Codex model_provider configured in CODEX_HOME.",
    )
    parser.add_argument(
        "--wire-api",
        choices=("chat", "responses"),
        default="responses",
        help="Override provider transport for local models.",
    )
    parser.add_argument(
        "--base-url-override",
        help="Unused diagnostic override; role proxy sets the local provider URL.",
    )
    parser.add_argument(
        "--upstream-base-url",
        default="http://127.0.0.1:4000",
        help="Upstream OpenAI-compatible endpoint used by the role-compatibility proxy.",
    )
    parser.add_argument(
        "--api-key-env",
        default="LITELLM_API_KEY",
        help="Environment variable name expected by the Codex provider.",
    )
    parser.add_argument(
        "--docker-api-key-container",
        default="litellm-litellm-1",
        help=(
            "Local Docker container from which to read a missing gateway "
            "credential without printing it."
        ),
    )
    parser.add_argument(
        "--docker-api-key-env-name",
        default="LITELLM_MASTER_KEY",
        help="Container environment variable containing the local gateway credential.",
    )
    parser.add_argument("--docker-path", default=shutil.which("docker"))
    parser.add_argument("--timeout", type=float, default=240)
    arguments = parser.parse_args()

    workspace = Path(arguments.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    codex_input = (
        Path(arguments.codex_path).expanduser() if arguments.codex_path else None
    )
    codex = codex_input.resolve() if codex_input else None
    if not codex or not codex.is_file() or not os.access(codex, os.X_OK):
        print(json.dumps({"ok": False, "error": "Codex executable not found"}))
        return 2

    api_key = os.environ.get(arguments.api_key_env)
    auth_source = "environment"
    if not api_key and arguments.docker_api_key_container:
        if not arguments.docker_path or not Path(arguments.docker_path).is_absolute():
            print(json.dumps({"ok": False, "error": "Docker executable not found"}))
            return 2
        try:
            inspect = subprocess.run(
                [
                    arguments.docker_path,
                    "inspect",
                    arguments.docker_api_key_container,
                    "--format",
                    "{{range .Config.Env}}{{println .}}{{end}}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            print(json.dumps({"ok": False, "error": f"Docker inspection failed: {error}"}))
            return 2
        if inspect.returncode != 0:
            print(json.dumps({"ok": False, "error": "Docker container inspection failed"}))
            return 2
        for entry in inspect.stdout.splitlines():
            if entry.startswith(f"{arguments.docker_api_key_env_name}="):
                api_key = entry.split("=", 1)[1]
                auth_source = "local_docker_gateway"
                break
    if not api_key:
        print(json.dumps({"ok": False, "error": f"{arguments.api_key_env} not available"}))
        return 2

    class RoleCompatibilityProxy(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            if self.path.endswith("/responses"):
                try:
                    payload = json.loads(body)
                    if isinstance(payload.get("input"), list):
                        for item in payload["input"]:
                            if item.get("role") == "developer":
                                item["role"] = "user"
                    body = json.dumps(payload, separators=(",", ":")).encode()
                except (json.JSONDecodeError, TypeError):
                    pass
            upstream = arguments.upstream_base_url.rstrip("/") + self.path
            with open("/tmp/asdi-role-proxy.log", "a") as log:
                log.write(
                    json.dumps(
                        {
                            "path": self.path,
                            "upstream": upstream,
                            "bytes": len(body),
                        }
                    )
                    + "\n"
                )
            request = Request(upstream, data=body, method="POST")
            for key, value in self.headers.items():
                if key.lower() not in {"host", "content-length", "connection"}:
                    request.add_header(key, value)
            try:
                response = urlopen(request, timeout=arguments.timeout + 30)
                status = response.status
                headers = dict(response.headers)
            except urllib.error.HTTPError as error:
                response = error
                status = error.code
                headers = dict(error.headers)
            self.send_response(status)
            for key, value in headers.items():
                if key.lower() not in {
                    "transfer-encoding",
                    "content-length",
                    "connection",
                    "keep-alive",
                }:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()

        def log_message(self, format_string, *args) -> None:
            return

    proxy_server = ThreadingHTTPServer(("127.0.0.1", 0), RoleCompatibilityProxy)
    proxy_port = proxy_server.server_address[1]
    proxy_thread = threading.Thread(target=proxy_server.serve_forever, daemon=True)
    proxy_thread.start()

    prompt = PROMPT_TEMPLATE.format(
        mission_id=arguments.mission_id,
        variant=arguments.variant,
        objective=arguments.objective,
    )
    last_message = workspace / "agent-last-message.txt"
    command = [
        str(codex),
        "exec",
        "--cd",
        str(workspace),
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "-m",
        arguments.model,
        "-c",
        f"model_provider={arguments.model_provider}",
        "-c",
        f'model_providers.{arguments.model_provider}.wire_api="{arguments.wire_api}"',
        "-c",
        f'model_providers.{arguments.model_provider}.base_url="http://127.0.0.1:{proxy_port}/v1"',
        "--output-last-message",
        str(last_message),
        "-c",
        "sandbox_workspace_write.network_access=false",
        prompt,
    ]
    environment = {
        "PATH": f"{codex_input.parent}:/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "HTTP_PROXY": arguments.proxy,
        "HTTPS_PROXY": arguments.proxy,
        "ALL_PROXY": arguments.proxy,
        "NO_PROXY": "localhost,127.0.0.1",
        arguments.api_key_env: api_key,
    }
    if arguments.isolate_codex_home:
        runtime_home = Path(tempfile.mkdtemp(prefix="asdi-codex-home-"))
        for name in ("config.toml", "models.json"):
            source = Path(arguments.codex_home) / name
            if source.is_file():
                shutil.copy2(source, runtime_home / name)
        environment["CODEX_HOME"] = str(runtime_home)
    else:
        environment["CODEX_HOME"] = arguments.codex_home
    environment[arguments.api_key_env] = api_key
    completed = subprocess.run(
        command,
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=arguments.timeout,
        check=False,
    )
    proxy_server.shutdown()
    proxy_server.server_close()
    proxy_thread.join(timeout=2)
    (workspace / "codex.stdout.log").write_text(completed.stdout)
    (workspace / "codex.stderr.log").write_text(completed.stderr)
    findings: list[str] = []
    if completed.returncode != 0:
        findings.append(f"Codex exited {completed.returncode}")
    if not (workspace / "app.py").is_file():
        findings.append("app.py was not created")
    manifest_path = workspace / "manifest.json"
    manifest = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            findings.append("manifest.json is not valid JSON")
    else:
        findings.append("manifest.json was not created")
    if manifest.get("fixture_agent") is not False:
        findings.append("manifest does not identify a live adapter")

    expected_load_ok = arguments.variant != "buggy"
    behavioral_checks = [
        (["--self-check"], 0),
        (["--handle", "--scenario", "normal", "--flag-enabled", "false"], 0),
        (
            ["--handle", "--scenario", "load", "--flag-enabled", "true"],
            0 if expected_load_ok else 1,
        ),
    ]
    for check_arguments, expected_exit_code in behavioral_checks:
        try:
            check = subprocess.run(
                [
                    sys.executable,
                    str(workspace / "app.py"),
                    *check_arguments,
                ],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if check.returncode != expected_exit_code:
                findings.append(
                    f"behavioral check failed ({' '.join(check_arguments)}): "
                    f"exit {check.returncode}, expected {expected_exit_code}"
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            findings.append(f"behavioral check failed: {error}")

    result = {
        "ok": not findings,
        "variant": arguments.variant,
        "codex_exit_code": completed.returncode,
        "model": arguments.model,
        "model_provider": arguments.model_provider,
        "auth_source": auth_source,
        "findings": findings,
        "billing_api_queried": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
