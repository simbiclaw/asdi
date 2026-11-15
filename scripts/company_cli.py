#!/usr/bin/env python3
"""Operational CLI for durable ASDI company state on one host."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from asdi.lifecycle import LifecycleStore, MissionGuardrails, ProductOps


SENSITIVE_KEYS = {"api_key", "authorization", "password", "secret", "token"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if any(marker in normalized for marker in SENSITIVE_KEYS):
                result[str(key)] = "REDACTED"
            else:
                result[str(key)] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if lowered.startswith("bearer ") or lowered.startswith("sk-"):
            return "REDACTED"
    return value


def _json_output(value: Any) -> Any:
    return json.dumps(_redact(value), indent=2, sort_keys=True)


def mission_snapshot(store: LifecycleStore, mission: dict[str, Any]) -> dict[str, Any]:
    state = store.load(mission["mission_id"])
    budget = dict(state.get("budget", {}))
    guardrails = state.get("guardrails", {})
    if budget and guardrails:
        elapsed = max(0.0, time.time() - budget.get("wall_clock_started_at", time.time()))
        budget["wall_clock_seconds_used"] = elapsed
        budget["wall_clock_seconds_remaining"] = max(
            0.0, float(guardrails.get("wall_clock_seconds", 0)) - elapsed
        )
        budget["turns_remaining"] = max(
            0, int(guardrails.get("max_turns", 0)) - int(budget.get("turns_used", 0))
        )
        budget["spend_usd_remaining"] = max(
            0.0,
            float(guardrails.get("max_spend_usd", 0))
            - float(budget.get("spend_usd", 0)),
        )
    return {
        "mission_id": state["mission_id"],
        "created_at": state["created_at"],
        "status": state["status"],
        "mission_kind": state["mission_kind"],
        "external_reference": state.get("external_reference"),
        "reset_generation": state.get("reset_generation", 1),
        "parent_mission_id": state.get("parent_mission_id"),
        "objective": state["objective"],
        "brief": state.get("brief"),
        "guardrails": guardrails,
        "budget": budget,
        "tasks": state.get("tasks", []),
        "artifacts": state.get("artifacts", []),
        "classification": state.get("classification"),
        "merge": state.get("merge"),
        "closed": state.get("closed", False),
    }


def product_summary(product: ProductOps) -> dict[str, Any]:
    state = json.loads(product.state_path.read_text()) if product.state_path.exists() else {}
    flags = json.loads(product.flags_path.read_text()) if product.flags_path.exists() else {}

    def read_jsonl(path: Path, limit: int = 20) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        lines = path.read_text().splitlines()
        return [json.loads(line) for line in lines[-limit:]]

    traffic_count = len(product.traffic_path.read_text().splitlines()) if product.traffic_path.exists() else 0

    return {
        "current_release": state.get("current_release"),
        "deployment_count": len(state.get("deployments", [])),
        "recent_deployments": state.get("deployments", [])[-5:],
        "flags": flags,
        "traffic_count": traffic_count,
        "recent_traffic": read_jsonl(product.traffic_path, 10),
        "recent_observations": read_jsonl(product.observations_path, 10),
        "recent_learning": read_jsonl(product.learning_path, 20),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate and query local ASDI company state.")
    parser.add_argument("--root", required=True, help="Company evidence/state root")
    commands = parser.add_subparsers(dest="command", required=True)

    admit = commands.add_parser("admit", help="Admit a mission and compile its brief")
    admit.add_argument("--objective", required=True)
    admit.add_argument("--why", required=True)
    admit.add_argument("--external-reference", required=True)
    admit.add_argument("--mission-kind", choices=("feature", "repair"), default="feature")
    admit.add_argument("--constraint", action="append", default=[])
    admit.add_argument("--parent-mission-id")
    admit.add_argument("--reset-generation", type=int, default=1)
    admit.add_argument("--max-turns", type=int, default=24)
    admit.add_argument("--max-spend-usd", type=float, default=2.0)
    admit.add_argument("--wall-clock-seconds", type=int, default=120)
    admit.add_argument("--decompose", action="store_true")

    missions = commands.add_parser("missions", help="List durable missions")
    missions.add_argument("--status")
    missions.add_argument("--mission-kind")
    missions.add_argument("--external-reference")

    show = commands.add_parser("show", help="Show a mission snapshot")
    group = show.add_mutually_exclusive_group(required=True)
    group.add_argument("--mission-id")
    group.add_argument("--external-reference")

    events = commands.add_parser("events", help="Read append-only mission events")
    events.add_argument("--mission-id", required=True)
    events.add_argument("--limit", type=int, default=100)

    product = commands.add_parser("product", help="Read product operations evidence")
    commands.add_parser("check", help="Validate durable roots")
    return parser


def main(argv: list[str] | None = None, *, stdout: Any = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    def output(value: Any) -> None:
        text = value if isinstance(value, str) else _json_output(value)
        if stdout is None:
            print(text)
        else:
            stdout.write(text + "\n")
    root = Path(arguments.root).resolve()
    store = LifecycleStore(root)

    if arguments.command == "admit":
        mission = store.create_mission(
            objective=arguments.objective,
            why=arguments.why,
            constraints=arguments.constraint,
            mission_kind=arguments.mission_kind,
            parent_mission_id=arguments.parent_mission_id,
            guardrails=MissionGuardrails(
                max_turns=arguments.max_turns,
                max_spend_usd=arguments.max_spend_usd,
                wall_clock_seconds=arguments.wall_clock_seconds,
            ),
            external_reference=arguments.external_reference,
            reset_generation=arguments.reset_generation,
        )
        mission_id = mission["mission_id"]
        if arguments.decompose:
            from asdi.lifecycle import MissionEngine

            MissionEngine(store).decompose(mission_id)
        output(_json_output(mission_snapshot(store, store.load(mission_id))))
        return 0

    if arguments.command == "missions":
        missions = store.list_missions(
            status=arguments.status,
            mission_kind=arguments.mission_kind,
            external_reference=arguments.external_reference,
        )
        output(_json_output([mission_snapshot(store, mission) for mission in missions]))
        return 0

    if arguments.command == "show":
        if arguments.mission_id:
            missions = [store.load(arguments.mission_id)]
        else:
            missions = store.find_by_external_reference(arguments.external_reference)
        if not missions:
            output(_json_output({"error": "mission_not_found"}))
            return 2
        snapshots = [mission_snapshot(store, mission) for mission in missions]
        output(_json_output(snapshots[0] if len(snapshots) == 1 else snapshots))
        return 0

    if arguments.command == "events":
        events = store.events(arguments.mission_id)
        output(_json_output(events[-max(0, arguments.limit):]))
        return 0

    if arguments.command == "product":
        output(_json_output(product_summary(ProductOps(root / "product"))))
        return 0

    if arguments.command == "check":
        product_root = root / "product"
        output(
            _json_output(
                {
                    "ok": root.exists(),
                    "root": str(root),
                    "missions_root": (root / "missions").exists(),
                    "product_root": product_root.exists(),
                }
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
