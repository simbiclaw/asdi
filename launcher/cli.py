#!/usr/bin/env python3
"""REV K launcher CLI: run, status, and kill."""

from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path

from asdi.governance import TRMLedger, paired_metrics
from asdi.lifecycle import LifecycleStore, MissionGuardrails, MergeAuthorization, ProductOps
from launcher.runner import DockerRuntime, REVKLauncher
from launcher.state import load_run_state, list_run_states


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ASDI REV K launcher")
    parser.add_argument("--root", required=True)
    parser.add_argument("--product-root", required=True)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--agent-image", default="safeclaw:cc-2.1.283")
    parser.add_argument("--agent-script")
    parser.add_argument("--docker", default=None)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", default="qwen3.6-35b-dspark-local")
    parser.add_argument("--codex-path", default=None)
    parser.add_argument("--proxy", default="http://127.0.0.1:7890")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run a REV K contract")
    run.add_argument("--contract", required=True)
    run.add_argument("--max-turns", type=int, default=24)
    run.add_argument("--max-spend-usd", type=float, default=2.0)
    run.add_argument("--minutes", type=int, default=10)
    status = commands.add_parser("status", help="Show a launcher run")
    status.add_argument("--run-id", required=True)
    listing = commands.add_parser("list", help="List launcher runs")
    kill = commands.add_parser("kill", help="Kill a running launcher process/container")
    kill.add_argument("--run-id", required=True)
    governance = commands.add_parser("governance", help="Show TRM and paired metrics")
    governance.add_argument("--window-days", type=int, default=7)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    runs_root = root / "runs"
    if args.command == "run":
        contract = json.loads(Path(args.contract).read_text())
        contract["guardrails"] = {
            "turns": args.max_turns,
            "spend_usd": args.max_spend_usd,
            "minutes": args.minutes,
            "tokens": None,
        }
        temporary = root / ".current-contract.json"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
        runtime = DockerRuntime(args.docker)
        launcher = REVKLauncher(
            root=root,
            product_root=Path(args.product_root),
            base_branch=args.base_branch,
            agent_image=args.agent_image,
            runtime=runtime,
            agent_script=args.agent_script,
            agent_default_cost_usd=0.0,
        )
        result = launcher.run(args.contract)
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))
        return 0 if result.status == "succeeded" else 3
    if args.command == "status":
        state = load_run_state(runs_root, args.run_id)
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    if args.command == "list":
        print(json.dumps(list_run_states(runs_root), indent=2, sort_keys=True))
        return 0
    if args.command == "kill":
        state = load_run_state(runs_root, args.run_id)
        pid = state.get("pid")
        if isinstance(pid, int):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        runtime = DockerRuntime(args.docker)
        container = state.get("container")
        if container:
            runtime.kill(container)
        state["status"] = "killed"
        state["killed_at"] = __import__("time").time()
        from launcher.state import atomic_json

        atomic_json(runs_root / args.run_id / "launcher-state.json", state)
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    if args.command == "governance":
        print(
            json.dumps(
                {
                    "trm": TRMLedger(root / "governance").snapshot(),
                    "metrics": paired_metrics(root, window_days=args.window_days),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
