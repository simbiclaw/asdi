#!/usr/bin/env python3
"""Builder-owned Claude Code adapter for REV K launcher runs.

The launcher owns guardrails and verification.  This adapter only launches the
CLI, forwards its structured stream, and records its Stop-hook observation.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path


def stop_hook(arguments: argparse.Namespace) -> int:
    evidence = Path("/evidence")
    evidence.mkdir(parents=True, exist_ok=True)
    record = {
        "hook": "Stop",
        "run_id": arguments.run_id,
        "commit": arguments.commit,
        "workspace": arguments.workspace,
        "launcher_verifier_remains_authoritative": True,
    }
    (evidence / "claude-stop-hook.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"event": "turn", "turn": 1}), flush=True)
    return 0


def configure_agent(workspace: Path, run_id: str, commit: str) -> Path:
    settings_dir = workspace / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    hook = settings_dir / "asdi-stop-hook.sh"
    hook.write_text(
        "#!/bin/sh\n"
        "/usr/bin/python3 /opt/asdi/claude_adapter.py "
        f"--stop-hook --workspace {shlex.quote(str(workspace))} "
        f"--run-id {shlex.quote(run_id)} --commit {shlex.quote(commit)}\n"
    )
    hook.chmod(0o700)
    placeholder = settings_dir / "asdi-placeholder-key.sh"
    placeholder.write_text("#!/bin/sh\nprintf 'asdi-egress-placeholder\\n'\n")
    placeholder.chmod(0o700)
    settings = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "timeout": 30, "command": str(hook)}
                    ],
                }
            ]
        },
        "apiKeyHelper": str(placeholder),
    }
    settings_path = settings_dir / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n")
    return settings_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--stop-hook", action="store_true")
    arguments = parser.parse_args()
    if arguments.stop_hook:
        return stop_hook(arguments)

    workspace = Path(arguments.workspace)
    settings_path = configure_agent(workspace, arguments.run_id, arguments.commit)
    model_base = os.environ.get("ASDI_MODEL_PROXY_URL", "").removesuffix("/v1")
    model = os.environ.get("ASDI_AGENT_MODEL", "qwen3.6-35b-dspark-local")
    objective = os.environ.get("ASDI_OBJECTIVE", "Complete the contracted work.")
    why = os.environ.get("ASDI_WHY", "")
    constraints = os.environ.get("ASDI_CONSTRAINTS", "")
    out_of_scope = os.environ.get("ASDI_OUT_OF_SCOPE", "")
    done_check = os.environ.get("ASDI_DONE_CHECK", "")
    prompt = "\n".join(
        [
            f"Objective: {objective}",
            f"Why: {why}",
            f"Constraints: {constraints}",
            f"Out of scope: {out_of_scope}",
            (
                "When implementation is complete, make the launcher's done_check "
                f"succeed: {done_check}"
            ),
            "Never print environment values or secrets. Stay inside /workspace.",
        ]
    )
    claude = shutil.which("claude") or "/home/sclaw/.local/bin/claude"
    if not claude:
        print(json.dumps({"error": "claude_cli_not_found"}), flush=True)
        return 2
    command = [
        claude,
        "--print",
        "--model",
        model,
        "--permission-mode",
        "bypassPermissions",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--output-format",
        "stream-json",
        "--verbose",
        "--settings",
        str(settings_path),
        prompt,
    ]
    child_environment = os.environ.copy()
    child_environment["ANTHROPIC_BASE_URL"] = model_base
    completed = subprocess.run(
        command,
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        env=child_environment,
    )
    evidence = Path("/evidence")
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "claude.stdout.log").write_text(completed.stdout)
    (evidence / "claude.stderr.log").write_text(completed.stderr)
    usage_emitted = False
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            print(json.dumps({"event": "turn", "turn": 1}), flush=True)
        result = event.get("result") if isinstance(event.get("result"), dict) else event
        usage = result.get("usage")
        if isinstance(usage, dict) and not usage_emitted:
            tokens = int(usage.get("input_tokens", 0)) + int(
                usage.get("output_tokens", 0)
            )
            cost = float(result.get("total_cost_usd", 0.0))
            print(
                json.dumps({"event": "usage", "tokens": tokens, "usd": cost}),
                flush=True,
            )
            usage_emitted = True
    if not usage_emitted:
        print(json.dumps({"event": "usage", "tokens": 0, "usd": 0.0}), flush=True)
    (evidence / "claude-result.json").write_text(
        json.dumps(
            {"exit_code": completed.returncode, "stream": "stream-json"},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
