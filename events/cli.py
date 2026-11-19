#!/usr/bin/env python3
"""Operational CLI for the local REV K event journal and PR gate."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import yaml

from .journal import EventJournal, LocalPoller, PollerState
from .merge_gate import evaluate_merge_packet
from .pr_gate import PRGate, deployment_decision, post_merge_check


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def load_gate_config(arguments: argparse.Namespace) -> tuple[dict[str, Any], dict[str, list[str]]]:
    class_config = yaml.safe_load(Path(arguments.class_config).read_text())
    feature_map = yaml.safe_load(Path(arguments.feature_map).read_text())
    if not isinstance(class_config, dict):
        raise ValueError("class config must be an object")
    if not isinstance(feature_map, dict):
        raise ValueError("feature map must be an object")
    return class_config, feature_map


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local ASDI event and PR gate control plane"
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-ref", default="main")
    parser.add_argument(
        "--class-config",
        type=Path,
        default=Path("config/classes.yaml"),
    )
    parser.add_argument(
        "--feature-map",
        type=Path,
        default=Path("config/coverage.yaml"),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    append = commands.add_parser("append-event")
    append.add_argument("--event-type", required=True)
    append.add_argument("--payload", required=True)

    catch_up = commands.add_parser("catch-up")
    catch_up.add_argument("--now", type=float, default=time.time())

    commands.add_parser("health")
    gate = commands.add_parser("gate")
    gate.add_argument("--payload", required=True)
    gate.add_argument("--packet-output", required=True)

    post_merge = commands.add_parser("post-merge")
    post_merge.add_argument("--payload", required=True)
    post_merge.add_argument("--result-output", required=True)

    deployment = commands.add_parser("deployment-decision")
    deployment.add_argument("--commit", required=True)
    deployment.add_argument("--main-results", required=True)
    deployment.add_argument("--decision-output", required=True)
    merge = commands.add_parser("merge-dry-run")
    merge.add_argument("--packet", required=True)
    merge.add_argument("--actor", required=True)
    merge.add_argument("--trm-level", default="T0")
    merge.add_argument("--result-output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    journal = EventJournal(root / "journal")
    state = PollerState(root / "state")

    if arguments.command == "append-event":
        event = journal.append(
            event_type=arguments.event_type,
            payload=load_json(arguments.payload),
        )
        write_json(root / "last-event.json", event)
        result = event
    elif arguments.command == "catch-up":
        class_config, feature_map = load_gate_config(arguments)
        gate = PRGate(
            class_config=class_config,
            feature_map=feature_map,
            base_ref=arguments.base_ref,
        )

        def handler(event: dict[str, Any]) -> None:
            if event["event_type"] != "github.pull_request":
                return
            result = gate.evaluate(event["payload"])
            packet_name = (
                f"pr-{result['pr_number']}-{result['head_sha'][:12]}.json"
            )
            write_json(root / "packets" / packet_name, result["packet"])
            write_json(root / "latest-policy.json", result)

        result = LocalPoller(
            journal=journal,
            state=state,
        ).catch_up(handler=handler, now=arguments.now)
        if not isinstance(result, dict):
            raise ValueError("catch-up returned no result")
        write_json(root / "last-catch-up.json", result)
    elif arguments.command == "health":
        result = LocalPoller(
            journal=journal,
            state=state,
        ).health(now=time.time())
        write_json(root / "poller-health.json", result)
    elif arguments.command == "gate":
        class_config, feature_map = load_gate_config(arguments)
        gate = PRGate(
            class_config=class_config,
            feature_map=feature_map,
            base_ref=arguments.base_ref,
        )
        result = gate.evaluate(load_json(arguments.payload))
        write_json(root / "latest-policy.json", result)
        write_json(Path(arguments.packet_output), result["packet"])
    elif arguments.command == "post-merge":
        result = post_merge_check(load_json(arguments.payload))
        write_json(root / "latest-post-merge.json", result)
        write_json(Path(arguments.result_output), result)
    elif arguments.command == "deployment-decision":
        result = deployment_decision(
            commit=arguments.commit,
            main_results=load_json(arguments.main_results),
        )
        write_json(root / "latest-deployment-decision.json", result)
        write_json(Path(arguments.decision_output), result)
    elif arguments.command == "merge-dry-run":
        result = evaluate_merge_packet(
            load_json(arguments.packet),
            actor=arguments.actor,
            trm_level=arguments.trm_level,
        )
        write_json(root / "latest-merge-dry-run.json", result)
        write_json(Path(arguments.result_output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
