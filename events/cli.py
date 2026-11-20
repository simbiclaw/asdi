#!/usr/bin/env python3
"""Operational CLI for the local REV K event journal and PR gate."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import yaml

from .config import DEFAULT_CONFIG_PATH, load_operational_defaults
from .journal import EventJournal, LocalPoller, PollerState
from .main_workflow import MainWorkflowStore
from .main_pipeline import run_main_verification_pipeline
from .merge_gate import evaluate_merge_packet
from .pr_workflow import PRWorkflowStore
from .pr_gate import PRGate, deployment_decision, post_merge_check
from .release_gate import release_readiness
from .review import ReviewCommand, review_event_payload, run_review
from .comment_gate import agent_claims_block, classify_comment
from .dispatcher import EventDispatcher
from .verification import main_verification_event_payload, verification_event_payload
from .verifier_command import VerificationCommand
from .github_reconciler import (
    GitHubCommand,
    GitHubReconciler,
    default_github_environment,
)
from .independent_audit import IndependentAuditStore
from .independent_audit import audit_template as build_independent_audit_template
from launcher.owner_decisions import OwnerDecisionLog
from .pipeline import run_pr_gate_pipeline


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
        default=Path("config/features.yaml"),
    )
    parser.add_argument(
        "--identities",
        type=Path,
        default=Path("config/identities.yaml"),
    )
    parser.add_argument(
        "--defaults",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
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
    readiness = commands.add_parser("release-readiness")
    readiness.add_argument("--commit", required=True)
    readiness.add_argument("--artifact-digest", required=True)
    readiness.add_argument("--readiness-output", required=True)
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
    review.add_argument("--timeout-seconds", type=float, default=None)
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
    review_event.add_argument("--timeout-seconds", type=float, default=None)
    review_event.add_argument("--result-output", required=True)
    verification_event = commands.add_parser("record-verification")
    verification_event.add_argument("--packet", required=True)
    verification_event.add_argument("--evidence", required=True)
    verification_event.add_argument(
        "--ci-status",
        choices=("pass", "fail", "blocked", "error"),
        required=True,
    )
    main_verification = commands.add_parser("record-main-verification")
    main_verification.add_argument("--commit", required=True)
    main_verification.add_argument("--evidence", required=True)
    main_verification.add_argument(
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
    reconcile = commands.add_parser("reconcile-github")
    reconcile.add_argument("--repository", required=True)
    reconcile.add_argument(
        "--gh",
        default="/opt/homebrew/bin/gh",
    )
    reconcile.add_argument(
        "--proxy",
        default="http://127.0.0.1:7890",
    )
    reconcile.add_argument("--timeout-seconds", type=float, default=None)
    pipeline = commands.add_parser("run-pr-gate")
    pipeline.add_argument("--pr-number", type=int, required=True)
    pipeline.add_argument("--evidence")
    pipeline.add_argument(
        "--ci-status",
        choices=("pass", "fail", "blocked", "error"),
        required=True,
    )
    pipeline.add_argument("--diff", required=True)
    pipeline.add_argument("--reviewer", action="append", required=True)
    pipeline.add_argument("--name", required=True)
    pipeline.add_argument(
        "--independent-family",
        choices=("true", "false", "unavailable"),
        required=True,
    )
    pipeline.add_argument("--timeout-seconds", type=float, default=None)
    pipeline.add_argument("--review-result-output", required=True)
    pipeline.add_argument("--actor", required=True)
    pipeline.add_argument("--trm-level", default="T0")
    audit_ingest = commands.add_parser("record-independent-audit")
    audit_ingest.add_argument("--report", required=True)
    audit_show = commands.add_parser("show-independent-audit")
    audit_show.add_argument("--pr-number", type=int, required=True)
    audit_show.add_argument("--head-sha", required=True)
    audit_template = commands.add_parser("audit-template")
    audit_template.add_argument("--pr-number", type=int, required=True)
    audit_template.add_argument("--head-sha", required=True)
    audit_template.add_argument("--output", required=True)
    pipeline.add_argument("--verifier", action="append")
    pipeline.add_argument("--verifier-name")
    pipeline.add_argument("--verifier-timeout-seconds", type=float, default=None)
    pipeline.add_argument("--verifier-result-output")
    main_pipeline = commands.add_parser("run-main-verification")
    main_pipeline.add_argument("--commit")
    main_pipeline.add_argument(
        "--ci-status",
        choices=("pass", "fail", "blocked", "error"),
        required=True,
    )
    main_pipeline.add_argument("--verifier", action="append", required=True)
    main_pipeline.add_argument("--verifier-name", required=True)
    main_pipeline.add_argument(
        "--verifier-timeout-seconds",
        type=float,
        default=None,
    )
    main_pipeline.add_argument("--verifier-result-output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    defaults = load_operational_defaults(arguments.defaults)
    stale_after_seconds = defaults.poller_stale_after_seconds
    if arguments.command in {"review", "review-event", "run-pr-gate"}:
        if arguments.timeout_seconds is None:
            arguments.timeout_seconds = defaults.review_timeout_seconds
    elif arguments.command == "reconcile-github" and arguments.timeout_seconds is None:
        arguments.timeout_seconds = defaults.github_reconciler_timeout_seconds
    if (
        arguments.command in {"run-pr-gate", "run-main-verification"}
        and arguments.verifier_timeout_seconds is None
    ):
        arguments.verifier_timeout_seconds = defaults.verifier_timeout_seconds
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
        dispatcher = EventDispatcher(
            root=root,
            workflow=workflow,
            main_workflow=main_workflow,
        )
        result = LocalPoller(
            journal=journal,
            state=state,
            stale_after_seconds=stale_after_seconds,
        ).catch_up(handler=dispatcher.handle, now=arguments.now)
        if not isinstance(result, dict):
            raise ValueError("catch-up returned no result")
        write_json(root / "last-catch-up.json", result)
    elif arguments.command == "reconcile-github":
        environment = default_github_environment(proxy_url=arguments.proxy)
        reconciler = GitHubReconciler(
            journal=journal,
            state_path=root / "github-reconciler-health.json",
            repository=arguments.repository,
            base_ref=arguments.base_ref,
            pr_command=GitHubCommand(
                argv=(
                    arguments.gh,
                    "pr",
                    "list",
                    "--repo",
                    arguments.repository,
                    "--state",
                    "open",
                    "--limit",
                    "100",
                    "--json",
                    "number,headRefOid,baseRefName,files",
                ),
                timeout_seconds=arguments.timeout_seconds,
                environment=environment,
            ),
            main_command=GitHubCommand(
                argv=(
                    arguments.gh,
                    "api",
                    f"repos/{arguments.repository}/commits/{arguments.base_ref}",
                    "--jq",
                    '{"sha": .sha}',
                ),
                timeout_seconds=arguments.timeout_seconds,
                environment=environment,
            ),
        )
        result = reconciler.reconcile()
        write_json(root / "last-github-reconciliation.json", result)
    elif arguments.command == "health":
        result = LocalPoller(
            journal=journal,
            state=state,
            stale_after_seconds=stale_after_seconds,
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
    elif arguments.command == "release-readiness":
        main_workflow = MainWorkflowStore(root / "main-workflow")
        result = release_readiness(
            commit=arguments.commit,
            artifact_digest=arguments.artifact_digest,
            main_state=main_workflow.current_state(arguments.commit),
            current_state=main_workflow.current_state(),
        )
        write_json(root / "latest-release-readiness.json", result)
        write_json(Path(arguments.readiness_output), result)
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
    elif arguments.command == "record-main-verification":
        event = journal.append(
            event_type="github.main_verification_completed",
            payload=main_verification_event_payload(
                commit=arguments.commit,
                evidence=load_json(arguments.evidence),
                ci_status=arguments.ci_status,
            ),
        )
        write_json(root / "last-main-verification-event.json", event)
        result = event
    elif arguments.command == "run-pr-gate":
        class_config, feature_map = load_gate_config(arguments)
        if arguments.evidence is not None and arguments.verifier:
            parser.error("use either --evidence or --verifier, not both")
        if arguments.evidence is None and not arguments.verifier:
            parser.error("one of --evidence or --verifier is required")
        if arguments.verifier and (
            not arguments.verifier_name or not arguments.verifier_result_output
        ):
            parser.error(
                "--verifier requires --verifier-name and --verifier-result-output"
            )
        workflow = PRWorkflowStore(
            root / "pr-workflow",
            class_config=class_config,
            feature_map=feature_map,
            base_ref=arguments.base_ref,
        )
        main_workflow = MainWorkflowStore(root / "main-workflow")
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
        verification_command = None
        if arguments.verifier:
            verification_command = VerificationCommand(
                name=arguments.verifier_name,
                argv=tuple(arguments.verifier),
                timeout_seconds=arguments.verifier_timeout_seconds,
            )
        result = run_pr_gate_pipeline(
            root=root,
            journal=journal,
            poller_state=state,
            stale_after_seconds=stale_after_seconds,
            workflow=workflow,
            main_workflow=main_workflow,
            pr_number=arguments.pr_number,
            evidence=(
                load_json(arguments.evidence)
                if arguments.evidence is not None
                else None
            ),
            verification_command=verification_command,
            verification_result_path=arguments.verifier_result_output,
            ci_status=arguments.ci_status,
            diff=Path(arguments.diff).read_text(),
            reviewer=reviewer,
            actor=arguments.actor,
            trm_level=arguments.trm_level,
            review_result_path=arguments.review_result_output,
        )
    elif arguments.command == "run-main-verification":
        main_workflow = MainWorkflowStore(root / "main-workflow")
        verification_command = VerificationCommand(
            name=arguments.verifier_name,
            argv=tuple(arguments.verifier),
            timeout_seconds=arguments.verifier_timeout_seconds,
            source="main",
        )
        result = run_main_verification_pipeline(
            root=root,
            journal=journal,
            poller_state=state,
            stale_after_seconds=stale_after_seconds,
            main_workflow=main_workflow,
            verification_command=verification_command,
            ci_status=arguments.ci_status,
            verification_result_path=arguments.verifier_result_output,
            commit=arguments.commit,
        )
    elif arguments.command == "record-independent-audit":
        result = IndependentAuditStore(root).ingest(
            load_json(arguments.report),
            decision_log=OwnerDecisionLog(root),
        )
        write_json(root / "latest-independent-audit-ingestion.json", result)
    elif arguments.command == "show-independent-audit":
        result = IndependentAuditStore(root).load(
            pr_number=arguments.pr_number,
            head_sha=arguments.head_sha,
            decision_log=OwnerDecisionLog(root),
        )
    elif arguments.command == "audit-template":
        result = build_independent_audit_template(
            decision_log=OwnerDecisionLog(root),
            pr_number=arguments.pr_number,
            head_sha=arguments.head_sha,
        )
        write_json(Path(arguments.output), result)
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
