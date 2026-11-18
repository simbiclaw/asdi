#!/usr/bin/env python3
"""Live Claude Code adapter for the REV K per-run egress proxy probe.

The launcher binds this adapter at ``/opt/asdi/fixture_agent.py``.  It receives
only the launcher's explicit environment: the model credential remains in the
egress-proxy process and is injected there.  The Stop hook is the adapter's own
launcher-visible completion check, not an agent claim of success.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import shutil
from pathlib import Path


PROMPT = """Use the Bash tool to run these commands from /workspace in order:
1. git clone --depth 1 https://github.com/octocat/Hello-World.git /tmp/asdi-git-clone
2. npm init -y
3. npm install --save-exact is-odd@3.0.1 --no-audit --no-fund --ignore-scripts --proxy "$HTTPS_PROXY" --https-proxy "$HTTPS_PROXY"
4. npm view is-odd version --proxy "$HTTPS_PROXY"

Then use the Write tool to create /workspace/proxy_probe.py. It must import the
installed is-odd package and, when run, print exactly this JSON and a newline:
{"git_clone":"pass","npm_package":"pass","model_endpoint":"configured"}

Finally use the Bash tool to run `python3 /workspace/proxy_probe.py`. Do not read
or print environment variable values. Do not modify files outside /workspace and
/tmp. Stop after the probe succeeds.
"""


def environment_names() -> list[str]:
    return sorted(os.environ)


def secret_observation(names: list[str]) -> dict[str, object]:
    forbidden = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)
    return {
        "names": names,
        "forbidden_names": [name for name in names if forbidden.search(name)],
        "values_recorded": False,
    }


def write_stop_hook(workspace: Path, run_id: str, commit: str) -> Path:
    helper = Path(os.environ.get("TMPDIR", "/tmp")) / "asdi-api-key-helper.sh"
    helper.write_text("#!/bin/sh\nprintf 'asdi-proxy-placeholder\\n'\n")
    helper.chmod(0o700)
    settings = {
        "apiKeyHelper": str(helper),
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "timeout": 30,
                            "command": (
                                "/usr/bin/python3 /opt/asdi/fixture_agent.py "
                                f"--stop-hook --workspace {workspace} "
                                f"--run-id {run_id} --commit {commit}"
                            ),
                        }
                    ],
                }
            ]
        }
    }
    path = Path(os.environ.get("TMPDIR", "/tmp")) / "asdi-claude-settings.json"
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n")
    return path


def validate_completion(workspace: Path, run_id: str, commit: str) -> int:
    evidence = Path("/evidence")
    checks = {
        "claude_stop_hook": (evidence / "claude-stop-hook.json").is_file(),
        "claude_result": (evidence / "claude-result.json").is_file(),
        "probe_source": (workspace / "proxy_probe.py").is_file(),
        "npm_package": (workspace / "node_modules" / "is-odd" / "package.json").is_file(),
        "npm_lockfile": (workspace / "package-lock.json").is_file(),
        "git_clone": Path("/tmp/asdi-git-clone/.git").is_dir(),
    }
    names = environment_names()
    observation = secret_observation(names)
    failures = [name for name, passed in checks.items() if not passed]
    if observation["forbidden_names"]:
        failures.append("credential-like_environment_names")
    record = {
        "schema": 1,
        "hook": "Stop",
        "run_id": run_id,
        "commit": commit,
        "checks": checks,
        "environment": observation,
        "failures": failures,
    }
    (evidence / "claude-stop-hook.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"event": "turn", "turn": 1}), flush=True)
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--stop-hook", action="store_true")
    arguments = parser.parse_args()
    workspace = Path(arguments.workspace)
    evidence = Path("/evidence")
    evidence.mkdir(parents=True, exist_ok=True)
    if arguments.stop_hook:
        return validate_completion(workspace, arguments.run_id, arguments.commit)

    environment = dict(os.environ)
    environment.update(
        {
            "ANTHROPIC_BASE_URL": environment.get("ASDI_MODEL_BASE_URL", "").removesuffix(
                "/v1"
            ),
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "DISABLE_AUTOUPDATER": "1",
            "npm_config_proxy": environment.get("HTTPS_PROXY", ""),
            "npm_config_https_proxy": environment.get("HTTPS_PROXY", ""),
        }
    )
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if not environment[name]:
            environment.pop(name)
    claude = shutil.which("claude") or "/home/sclaw/.local/bin/claude"
    if not claude:
        print(json.dumps({"error": "claude_cli_not_found"}), flush=True)
        return 2
    settings = write_stop_hook(workspace, arguments.run_id, arguments.commit)
    command = [
        claude,
        "--print",
        "--model",
        os.environ.get("ASDI_CLAUDE_MODEL", "qwen3.6-35b-dspark-local"),
        "--permission-mode",
        "bypassPermissions",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--include-hook-events",
        "--setting-sources",
        "",
        "--tools",
        "Bash,Write,Read",
        "--no-chrome",
        "--settings",
        str(settings),
        PROMPT,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
            timeout=420,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        (evidence / "claude-result.json").write_text(
            json.dumps({"error": "claude_timeout", "detail": str(error)}, indent=2) + "\n"
        )
        print(json.dumps({"event": "turn", "turn": 1}), flush=True)
        return 1

    stdout = completed.stdout
    stderr = completed.stderr
    (workspace / "claude.stdout.log").write_text(stdout)
    (workspace / "claude.stderr.log").write_text(stderr)
    result: dict[str, object] = {"exit_code": completed.returncode}
    try:
        parsed = json.loads(stdout)
        if isinstance(parsed, dict):
            result["claude"] = parsed
            usage = parsed.get("usage")
            cost = parsed.get("total_cost_usd", 0.0)
            if isinstance(usage, dict):
                input_tokens = int(usage.get("input_tokens", 0))
                output_tokens = int(usage.get("output_tokens", 0))
                print(
                    json.dumps(
                        {
                            "event": "usage",
                            "tokens": input_tokens + output_tokens,
                            "usd": float(cost),
                        }
                    ),
                    flush=True,
                )
    except json.JSONDecodeError:
        result["stdout_is_json"] = False
    (evidence / "claude-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    if completed.returncode != 0:
        print(json.dumps({"event": "turn", "turn": 1}), flush=True)
        return completed.returncode
    print(json.dumps({"event": "turn", "turn": 1}), flush=True)
    hook = validate_completion(workspace, arguments.run_id, arguments.commit)
    return hook


if __name__ == "__main__":
    raise SystemExit(main())
