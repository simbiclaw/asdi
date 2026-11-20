"""Append-only local error records (no external network or push channel)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Sequence

VALID_SEVERITIES = {"debug", "info", "warning", "error", "critical"}


class ErrorTrackerError(ValueError):
    """Raised for an invalid error record or a corrupt tracker file."""


class ErrorTracker:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self._lock = threading.Lock()

    def record(
        self,
        *,
        source: str,
        severity: str,
        message: str,
        context: dict[str, Any] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(source, str) or not source.strip():
            raise ErrorTrackerError("source is required")
        if severity not in VALID_SEVERITIES:
            raise ErrorTrackerError(f"severity must be one of {sorted(VALID_SEVERITIES)}")
        if not isinstance(message, str) or not message.strip():
            raise ErrorTrackerError("message is required")
        if context is not None and not isinstance(context, dict):
            raise ErrorTrackerError("context must be a JSON object")
        entry = {
            "schema_version": "asdi.error-record/v1",
            "recorded_at": occurred_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": source,
            "severity": severity,
            "message": message,
            "context": context or {},
        }
        payload = json.dumps(entry, sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def iter_records(self) -> Iterator[dict[str, Any]]:
        if not self.path.is_file():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ErrorTrackerError(
                        f"corrupt error record at {self.path}:{line_number}: {error}"
                    ) from error
                if not isinstance(entry, dict):
                    raise ErrorTrackerError(
                        f"error record at {self.path}:{line_number} is not an object"
                    )
                yield entry

    def tail(self, limit: int = 20) -> list[dict[str, Any]]:
        if limit < 1:
            raise ErrorTrackerError("limit must be at least one")
        return list(self.iter_records())[-limit:]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asdi-phase7-error-tracker")
    parser.add_argument("--log", required=True, help="path to the append-only local log")
    commands = parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record")
    record.add_argument("--source", required=True)
    record.add_argument("--severity", required=True, choices=sorted(VALID_SEVERITIES))
    record.add_argument("--message", required=True)
    record.add_argument("--context-json", default="{}")

    tail = commands.add_parser("tail")
    tail.add_argument("--limit", type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    tracker = ErrorTracker(arguments.log)
    try:
        if arguments.command == "record":
            try:
                context = json.loads(arguments.context_json)
            except json.JSONDecodeError as error:
                raise ErrorTrackerError(f"invalid context JSON: {error}") from error
            result: dict[str, Any] | list[dict[str, Any]] = tracker.record(
                source=arguments.source,
                severity=arguments.severity,
                message=arguments.message,
                context=context,
            )
        else:
            result = tracker.tail(arguments.limit)
    except ErrorTrackerError as error:
        print(f"error tracker refused record: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
