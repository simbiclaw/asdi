"""Append-only durable records for decisions reserved to the ASDI owner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "asdi.owner-decision/v1"
DECISION_TYPES = {
    "independent_verifier": {
        "readonly_audit_wrapper",
        "owner_invoked_audit",
        "other_enforced_runtime",
    },
    "phase3_pilot": {
        "select_existing_pilot",
        "approve_synthetic_toy_notes",
        "defer_phase3",
    },
}
FORBIDDEN_TOKEN_MARKERS = ("api_key", "authorization", "password", "secret", "token")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def record_digest(record: dict[str, Any]) -> str:
    payload = {key: item for key, item in record.items() if key != "record_sha256"}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


class OwnerDecisionLog:
    """Hash-chained JSONL decision records under the ASDI state root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "owner-decisions.jsonl"

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]

    def latest(self, decision_type: str | None = None) -> dict[str, Any] | None:
        matches = [
            record
            for record in self.records()
            if decision_type is None or record["decision_type"] == decision_type
        ]
        return matches[-1] if matches else None

    def record(
        self,
        *,
        decision_type: str,
        choice: str,
        decided_by: str,
        decision_reference: str,
        direction: str,
        selected_path: str | None = None,
        runtime_command: list[str] | None = None,
    ) -> dict[str, Any]:
        if decision_type not in DECISION_TYPES:
            raise ValueError(f"unknown decision type: {decision_type}")
        allowed = DECISION_TYPES[decision_type]
        if choice not in allowed:
            raise ValueError(f"choice must be one of: {', '.join(sorted(allowed))}")
        if not decided_by.strip() or not decision_reference.strip() or not direction.strip():
            raise ValueError("decided_by, decision_reference and direction are required")
        selected_path = selected_path.strip() if selected_path else None
        if choice == "select_existing_pilot" and not selected_path:
            raise ValueError("an existing pilot requires selected_path")
        if selected_path and (
            not Path(selected_path).is_absolute() or not Path(selected_path).is_dir()
        ):
            raise ValueError("selected pilot path must be an existing absolute directory")
        if choice != "select_existing_pilot":
            selected_path = None
        runtime_command = list(runtime_command or [])
        if decision_type == "independent_verifier" and runtime_command:
            if not runtime_command or not Path(runtime_command[0]).is_absolute():
                raise ValueError("runtime command executable must be absolute")
            if any(
                marker in token.lower()
                for token in runtime_command
                for marker in FORBIDDEN_TOKEN_MARKERS
            ):
                raise ValueError("runtime command may not contain credential-like names")
        elif runtime_command:
            runtime_command = []

        previous = self.records()
        previous_hash = record_digest(previous[-1]) if previous else None
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record = {
            "schema_version": SCHEMA_VERSION,
            "decision_id": f"owner_decision_{uuid.uuid4()}",
            "recorded_at": now,
            "decision_type": decision_type,
            "choice": choice,
            "selected_path": selected_path,
            "runtime_command": runtime_command,
            "decided_by": decided_by.strip(),
            "decision_reference": decision_reference.strip(),
            "direction": direction.strip(),
            "previous_record_sha256": previous_hash,
        }
        record["record_sha256"] = record_digest(record)
        with self.path.open("a") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def verify(self) -> dict[str, Any]:
        records = self.records()
        if len({line for line in self.path.read_text().splitlines() if line}) != len(records):
            return {
                "records": len(records),
                "valid": False,
                "failures": ["duplicate JSONL record"],
            }
        if len({line for line in self.path.read_text().splitlines() if line}) != len(records):
            return {
                "records": len(records),
                "valid": False,
                "failures": ["duplicate JSONL record"],
            }
        failures: list[str] = []
        previous_hash = None
        for index, record in enumerate(records, start=1):
            expected_previous = previous_hash
            if record.get("previous_record_sha256") != expected_previous:
                failures.append(f"record {index} previous hash mismatch")
            if record_digest(record) != record.get("record_sha256"):
                failures.append(f"record {index} hash mismatch")
            previous_hash = record.get("record_sha256")
        return {"records": len(records), "valid": not failures, "failures": failures}

    def status(self) -> dict[str, Any]:
        verification = self.verify()
        decisions: dict[str, Any] = {}
        for decision_type in DECISION_TYPES:
            record = self.latest(decision_type)
            decisions[decision_type] = {
                "recorded": record is not None,
                "choice": record.get("choice") if record else None,
                "decision_id": record.get("decision_id") if record else None,
                "selected_path": record.get("selected_path") if record else None,
            }
        pilot_choice = decisions["phase3_pilot"]["choice"]
        decisions["phase3_pilot"]["phase3_can_start"] = pilot_choice in {
            "select_existing_pilot",
            "approve_synthetic_toy_notes",
        }
        return {
            "log_valid": verification["valid"],
            "verification": verification,
            "decisions": decisions,
            "ready_for_next_phase": verification["valid"] and all(
                item["recorded"] for item in decisions.values()
            ),
            "pending": [
                decision_type
                for decision_type, item in decisions.items()
                if not item["recorded"]
            ],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operate owner decision records")
    parser.add_argument("--root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record")
    record.add_argument("--decision-type", choices=tuple(DECISION_TYPES), required=True)
    record.add_argument("--choice", required=True)
    record.add_argument("--decided-by", required=True)
    record.add_argument("--decision-reference", required=True)
    record.add_argument("--direction", required=True)
    record.add_argument("--selected-path")
    record.add_argument("--runtime-command", action="append")
    commands.add_parser("list")
    commands.add_parser("verify")
    commands.add_parser("status")
    arguments = parser.parse_args(argv)
    log = OwnerDecisionLog(arguments.root)
    if arguments.command == "record":
        result = log.record(
            decision_type=arguments.decision_type,
            choice=arguments.choice,
            decided_by=arguments.decided_by,
            decision_reference=arguments.decision_reference,
            direction=arguments.direction,
            selected_path=arguments.selected_path,
            runtime_command=arguments.runtime_command,
        )
    elif arguments.command == "list":
        result = log.records()
    elif arguments.command == "verify":
        result = log.verify()
    else:
        result = log.status()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if arguments.command != "verify" or result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
