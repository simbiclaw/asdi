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
from .main_workflow import MainWorkflowStore
from .merge_gate import evaluate_merge_packet
from .pr_workflow import PRWorkflowStore
from .pr_gate import PRGate, deployment_decision, post_merge_check
from .review import ReviewCommand, review_event_payload, run_review
from .comment_gate import agent_claims_block, classify_comment
from .verification import verification_event_payload


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
    parser.add_argument(
        "--identities",
        type=Path,
        default=Path("config/identities.yaml"),
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
    review = commands.add_parser("review")
    review.add_argument("--packet", required=True)
    review.add_argument("--diff", required=True)
    review.add_argument("--reviewer", action="append", required=True)
    review.add_argument("--name", required=True)
    review.add_argument(
        "--independent-family",
        choices=("true", "false", "unavailable"),
        required=True,
    )
    review.add_argument("--timeout-seconds", type=float, default=600.0)
    review.add_argument("--result-output", required=True)
    review_event = commands.add_parser("review-event")
    review_event.add_argument("--packet", required=True)
    review_event.add_argument("--diff", required=True)
    review_event.add_argument("--reviewer", action="append", required=True)
    review_event.add_argument("--name", required=True)
    review_event.add_argument(
        "--independent-family",
        choices=("true", "false", "unavailable"),
        required=True,
    )
    review_event.add_argument("--timeout-seconds", type=float, default=600.0)
    review_event.add_argument("--result-output", required=True)
    verification_event = commands.add_parser("record-verification")
    verification_event.add_argument("--packet", required=True)
    verification_event.add_argument("--evidence", required=True)
    verification_event.add_argument(
        "--ci-status",
        choices=("pass", "fail", "blocked", "error"),
        required=True,
    )
    merge = commands.add_parser("merge-dry-run")
    merge.add_argument("--packet", required=True)
    merge.add_argument("--actor", required=True)
    merge.add_argument("--trm-level", default="T0")
    merge.add_argument("--result-output", required=True)
    comment = commands.add_parser("comment-gate")
    comment.add_argument("--author", required=True)
    comment.add_argument("--body", required=True)
    comment.add_argument("--allowed-resumer", action="append", required=True)
    claims = commands.add_parser("agent-claims-block")
    claims.add_argument("--text", required=True)
    claims.add_argument("--max-chars", type=int, default=12_000)
    review_input = commands.add_parser("review-input")
    review_input.add_argument("--packet", required=True)
    review_input.add_argument("--diff", required=True)
    review_input.add_argument("--agent-claims", required=True)
    review_input.add_argument("--output-dir", required=True)
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
        workflow = PRWorkflowStore(
            root / "pr-workflow",
            class_config=class_config,
            feature_map=feature_map,
            base_ref=arguments.base_ref,
        )
        main_workflow = MainWorkflowStore(root / "main-workflow")
        def handler(event: dict[str, Any]) -> None:
            if event["event_type"] in {
                "github.push",
                "github.main_verification_completed",
            }:
                result = main_workflow.apply(event)
                write_json(
                    root / "main-workflow-results" / f"event-{event['event_id']}.json",
                    result,
                )
                write_json(root / "latest-main-workflow.json", result)
                return
            if event["event_type"] not in {
                "github.pull_request",
                "github.verification_completed",
                "github.review_completed",
            }:
                return
            result = workflow.apply(event)
            result_id = int(event["event_id"])
            write_json(
                root / "workflow-results" / f"event-{result_id}.json",
                result,
            )
            write_json(root / "latest-pr-workflow.json", result)
            if result["gate"] is not None:
                write_json(root / "latest-policy.json", result["gate"])
                packet = result["packet"]
                packet_name = (
                    f"pr-{packet['pr_number']}-{packet['head_sha'][:12]}.json"
                )
                write_json(root / "packets" / packet_name, packet)

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
    elif arguments.command in {"review", "review-event"}:
        reviewer = ReviewCommand(
            name=arguments.name,
            argv=tuple(arguments.reviewer),
            timeout_seconds=arguments.timeout_seconds,
            independent_family=(
                True
                if arguments.independent_family == "true"
                else False
                if arguments.independent_family == "false"
                else "unavailable"
            ),
        )
        packet = load_json(arguments.packet)
        result = run_review(
            packet=packet,
            diff=Path(arguments.diff).read_text(),
            command=reviewer,
        )
        write_json(root / "latest-review.json", result)
        write_json(Path(arguments.result_output), result)
        if arguments.command == "review-event":
            event = journal.append(
                event_type="github.review_completed",
                payload=review_event_payload(packet=packet, result=result),
            )
            write_json(root / "last-review-event.json", event)
            result = event
    elif arguments.command == "record-verification":
        event = journal.append(
            event_type="github.verification_completed",
            payload=verification_event_payload(
                packet=load_json(arguments.packet),
                evidence=load_json(arguments.evidence),
                ci_status=arguments.ci_status,
            ),
        )
        write_json(root / "last-verification-event.json", event)
        result = event
    elif arguments.command == "comment-gate":
        identities = yaml.safe_load(arguments.identities.read_text())
        result = classify_comment(
            author=arguments.author,
            body=arguments.body,
            allowed_comment_resumers=identities.get(
                "allowed_comment_resumers",
                [],
            ),
        )
        write_json(root / "latest-comment-boundary.json", result)
    elif arguments.command == "agent-claims-block":
        result = agent_claims_block(arguments.text, max_chars=arguments.max_chars)
        write_json(root / "latest-agent-claims-block.json", result)
    elif arguments.command == "review-input":
        claims = agent_claims_block(arguments.agent_claims)
        output_dir = Path(arguments.output_dir)
        write_json(output_dir / "review-packet.json", load_json(arguments.packet))
        (output_dir / "changed.diff").write_text(arguments.diff)
        write_json(output_dir / "agent-claims.json", claims)
        result = claims
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
