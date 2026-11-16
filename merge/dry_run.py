#!/usr/bin/env python3
"""Fail-closed direct-merge policy dry run for ASDI REV K Phase 0."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_STATUSES = {"ci", "asdi/policy"}
ALLOWED_MERGE_IDENTITY = "merge-bot"
REFUSED_MERGE_IDENTITIES = {"archon", "agents"}


def evaluate(
    *,
    actor: str,
    statuses: set[str],
    up_to_date: bool,
    classification: str,
    trm_level: str = "T0",
    config_path: Path | None = None,
) -> dict[str, Any]:
    rules_fired: list[str] = []
    if actor in REFUSED_MERGE_IDENTITIES:
        rules_fired.append("R1-agent-or-status-identity-refused")
    if actor != ALLOWED_MERGE_IDENTITY:
        rules_fired.append("R1-only-merge-identity-can-merge")
    missing = sorted(REQUIRED_STATUSES - statuses)
    if missing:
        rules_fired.append(f"R9-required-status-missing:{','.join(missing)}")
    if not up_to_date:
        rules_fired.append("R9-branch-not-up-to-date")
    if classification == "judgment":
        rules_fired.append("R-judgment-requires-human")
    if trm_level == "T0":
        rules_fired.append("R-TRM-T0-human-merge")

    if "R1-agent-or-status-identity-refused" in rules_fired:
        decision = "refused"
        reason = "agent or status identity cannot merge"
    elif actor != ALLOWED_MERGE_IDENTITY:
        decision = "human_required"
        reason = "only merge-bot may merge automatically"
    elif missing or not up_to_date:
        decision = "blocked"
        reason = "required checks or branch state are not green"
    elif classification == "judgment" or trm_level == "T0":
        decision = "human_required"
        reason = "governance requires a human merge"
    else:
        decision = "eligible"
        reason = "all Pass 1 merge conditions are green"

    return {
        "decision": decision,
        "actor": actor,
        "classification": classification,
        "trm_level": trm_level,
        "required_statuses": sorted(REQUIRED_STATUSES),
        "observed_statuses": sorted(statuses),
        "up_to_date": up_to_date,
        "rules_fired": rules_fired,
        "reason": reason,
        "config_path": str(config_path) if config_path else "built-in Phase 0 policy",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", required=True)
    parser.add_argument("--status", action="append", default=[])
    parser.add_argument("--classification", default="agent-mergeable")
    parser.add_argument("--trm-level", default="T0")
    parser.add_argument("--not-up-to-date", action="store_true")
    parser.add_argument("--output")
    arguments = parser.parse_args()
    result = evaluate(
        actor=arguments.actor,
        statuses=set(arguments.status),
        up_to_date=not arguments.not_up_to_date,
        classification=arguments.classification,
        trm_level=arguments.trm_level,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        Path(arguments.output).write_text(rendered)
    else:
        print(rendered, end="")
    return 0 if result["decision"] != "refused" else 2


if __name__ == "__main__":
    raise SystemExit(main())
