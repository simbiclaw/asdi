#!/usr/bin/env python3
"""REV K launcher CLI: run, status, and kill."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from pathlib import Path

import yaml

from events.config import load_pilot_config

from asdi.governance import TRMLedger, paired_metrics
from asdi.lifecycle import LifecycleStore, MissionGuardrails, MergeAuthorization, ProductOps
from launcher.contract import load_contract
from launcher.runner import DockerRuntime, REVKLauncher
from launcher.state import atomic_json, load_run_state, list_run_states


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ASDI REV K launcher")
    parser.add_argument("--root", required=True)
    parser.add_argument("--product-root", default=None)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--agent-image", default="safeclaw:cc-2.1.283")
    parser.add_argument(
        "--agent-adapter",
        choices=("fixture", "claude"),
        default="fixture",
    )
    parser.add_argument("--verifier-image", default=None)
    parser.add_argument("--agent-script")
    parser.add_argument("--docker", default=None)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", default="qwen3.6-35b-dspark-local")
    parser.add_argument("--codex-path", default=None)
    parser.add_argument("--proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--proxy-image", default="safeclaw-us-egress:cc-2.1.283")
    parser.add_argument("--egress-network", default="asdi-egress")
    parser.add_argument(
        "--model-endpoint",
        default="http://host.docker.internal:4000/v1",
    )
    parser.add_argument("--model-key-env", default="LITELLM_MASTER_KEY")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run a REV K contract")
    run.add_argument("contract", nargs="?")
    run.add_argument("--contract", dest="contract_option")
    run.add_argument("--max-turns", type=int, default=None)
    run.add_argument("--max-tokens", type=int, default=None)
    run.add_argument("--max-spend-usd", type=float, default=None)
    run.add_argument("--minutes", type=int, default=None)
    run.add_argument("--agent-cost-usd", type=float, default=0.0)
    status = commands.add_parser("status", help="Show a launcher run")
    status.add_argument("--run-id", required=True)
    pause = commands.add_parser("pause", help="Pause a running launcher run")
    pause.add_argument("--run-id", required=True)
    resume = commands.add_parser("resume", help="Resume a paused launcher checkpoint")
    resume.add_argument("--checkpoint", required=True)
    listing = commands.add_parser("list", help="List launcher runs")
    kill = commands.add_parser("kill", help="Kill a running launcher process/container")
    kill.add_argument("--run-id", required=True)
    governance = commands.add_parser("governance", help="Show TRM and paired metrics")
    governance.add_argument("--window-days", type=int, default=7)
    verify = commands.add_parser("verify", help="Verify one exact revision without an agent")
    verify.add_argument("--revision", required=True)
    verify.add_argument("--source", choices=("pr-head", "main"), default="pr-head")
    verify.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    product_root = (
        Path(args.product_root).resolve()
        if args.product_root
        else load_pilot_config().product_root.resolve()
    )
    runs_root = root / "runs"
    if args.command == "run":
        if args.contract and args.contract_option:
            parser.error("use either a positional contract or --contract, not both")
        contract_path = args.contract_option or args.contract
        if not contract_path:
            parser.error("a contract path is required")
        source = Path(contract_path)
        contract = (
            yaml.safe_load(source.read_text())
            if source.suffix.lower() in {".yaml", ".yml"}
            else json.loads(source.read_text())
        )
        if not isinstance(contract, dict):
            parser.error("contract must be an object")
        guardrails = contract["guardrails"]
        if args.max_turns is not None:
            guardrails["turns"] = args.max_turns
        if args.max_tokens is not None:
            guardrails["tokens"] = args.max_tokens
        if args.max_spend_usd is not None:
            guardrails["spend_usd"] = args.max_spend_usd
        if args.minutes is not None:
            guardrails["minutes"] = args.minutes
        suffix = (
            source.suffix.lower()
            if source.suffix.lower() in {".json", ".yaml", ".yml"}
            else ".json"
        )
        temporary = root / f".current-contract{suffix}"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            yaml.safe_dump(contract, sort_keys=True)
            if suffix in {".yaml", ".yml"}
            else json.dumps(contract, indent=2, sort_keys=True) + "\n"
        )
        contract = load_contract(temporary)
        runtime = DockerRuntime(args.docker)
        launcher = REVKLauncher(
            root=root,
            product_root=product_root,
            base_branch=args.base_branch,
            agent_image=args.agent_image,
            agent_adapter=args.agent_adapter,
            proxy_image=args.proxy_image,
            egress_network=args.egress_network,
            model_endpoint=args.model_endpoint,
            model_key_env=args.model_key_env,
            runtime=runtime,
            agent_script=args.agent_script,
            agent_default_cost_usd=args.agent_cost_usd,
        )
        result = launcher.run(temporary)
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))
        return 0 if result.status == "succeeded" else 3
    if args.command == "status":
        state = load_run_state(runs_root, args.run_id)
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    if args.command == "pause":
        state = load_run_state(runs_root, args.run_id)
        if state.get("status") != "running":
            parser.error(f"run {args.run_id} is not running")
        pid = state.get("pid")
        if isinstance(pid, int):
            try:
                os.kill(pid, signal.SIGSTOP)
            except ProcessLookupError:
                pass
        container = state.get("container")
        if container:
            DockerRuntime(args.docker).pause(container)
        state["status"] = "paused"
        state["paused_at"] = time.time()
        state["pause_checkpoint"] = args.run_id
        atomic_json(runs_root / args.run_id / "launcher-state.json", state)
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0
    if args.command == "resume":
        state = load_run_state(runs_root, args.checkpoint)
        if state.get("status") != "paused":
            parser.error(f"checkpoint {args.checkpoint} is not paused")
        pid = state.get("pid")
        if isinstance(pid, int):
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        container = state.get("container")
        if container:
            DockerRuntime(args.docker).unpause(container)
        state["status"] = "running"
        state["resumed_at"] = time.time()
        state.pop("paused_at", None)
        atomic_json(runs_root / args.checkpoint / "launcher-state.json", state)
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
        egress_container = state.get("egress_container")
        if egress_container:
            runtime.stop_proxy(egress_container)
        for name in (
            state.get("network"),
            state.get("evidence_volume"),
            state.get("workspace_volume"),
            state.get("base_volume"),
        ):
            if name:
                if name == state.get("network"):
                    runtime.remove_network(name)
                else:
                    runtime.remove_volume(name)
        state["status"] = "killed"
        state["killed_at"] = time.time()
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
    if args.command == "verify":
        launcher = REVKLauncher(
            root=root,
            product_root=product_root,
            base_branch=args.base_branch,
            verifier_image=args.verifier_image,
            runtime=DockerRuntime(args.docker),
        )
        result = launcher.verify_revision(args.revision, source=args.source)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered)
        print(rendered, end="")
        return 0 if result["status"] == "succeeded" else 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
