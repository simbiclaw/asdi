"""Local flag file with default-off flags and an expiry sweep."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from ci.approval import ApprovalError, utc_now, write_json_atomic

FLAG_SCHEMA = "asdi.flags/v1"
ISSUE_SCHEMA = "asdi.cleanup-issue/v1"
FLAG_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
CLASSIFICATION = "judgment"


class FlagError(ValueError):
    """Raised for an invalid flag transition."""


def _empty_document() -> dict[str, Any]:
    return {"schema_version": FLAG_SCHEMA, "flags": {}}


def load_flags(path: str | Path) -> dict[str, Any]:
    flag_path = Path(path).resolve()
    if not flag_path.exists():
        return _empty_document()
    try:
        document = json.loads(flag_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FlagError(f"flag file is not valid JSON: {error}") from error
    if not isinstance(document, dict) or document.get("schema_version") != FLAG_SCHEMA:
        raise FlagError(f"unsupported flag file schema: {flag_path}")
    flags = document.get("flags")
    if not isinstance(flags, dict):
        raise FlagError("flag file has no flags object")
    return document


def _save_flags(path: str | Path, document: dict[str, Any]) -> Path:
    return write_json_atomic(path, document)


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not FLAG_NAME.fullmatch(name):
        raise FlagError("flag name must be lowercase with letters, digits, '_' or '-'")
    return name


def _validate_decision(decision: str) -> str:
    if not isinstance(decision, str) or not decision.strip():
        raise FlagError("a decision reference is required for every flag state change")
    return decision.strip()


def _parse_expiry(expires_at: str) -> str:
    if not isinstance(expires_at, str) or not expires_at:
        raise FlagError("an ISO-8601 expiry with a timezone is required")
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise FlagError(f"invalid expiry timestamp: {expires_at}") from error
    if parsed.tzinfo is None:
        raise FlagError("expiry timestamp must include a timezone")
    return expires_at


def status(path: str | Path, name: str | None = None) -> dict[str, Any]:
    document = load_flags(path)
    flags = document["flags"]
    if name is not None:
        entry = flags.get(_validate_name(name))
        if entry is None:
            return {"schema_version": FLAG_SCHEMA, "flag": name, "enabled": False, "exists": False}
        return {
            "schema_version": FLAG_SCHEMA,
            "flag": name,
            "enabled": entry.get("enabled") is True,
            "exists": True,
            "entry": entry,
        }
    return {
        "schema_version": FLAG_SCHEMA,
        "flags": {
            flag_name: {"enabled": entry.get("enabled") is True}
            for flag_name, entry in sorted(flags.items())
        },
    }


def set_flag(
    path: str | Path,
    name: str,
    *,
    decision: str,
    expires_at: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    exact_name = _validate_name(name)
    document = load_flags(path)
    entry = {
        "enabled": True,
        "decision_reference": _validate_decision(decision),
        "expires_at": _parse_expiry(expires_at),
        "classification": CLASSIFICATION,
        "merge_policy_changed": False,
        "updated_at": updated_at or utc_now(),
    }
    document["flags"][exact_name] = entry
    _save_flags(path, document)
    return {"flag": exact_name, "state": "set", "entry": entry}


def keep_flag(
    path: str | Path,
    name: str,
    *,
    decision: str,
    expires_at: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    exact_name = _validate_name(name)
    document = load_flags(path)
    if exact_name not in document["flags"]:
        raise FlagError(f"cannot keep unknown flag: {exact_name}")
    entry = dict(document["flags"][exact_name])
    entry["enabled"] = True
    entry["decision_reference"] = _validate_decision(decision)
    entry["expires_at"] = _parse_expiry(expires_at)
    entry["classification"] = CLASSIFICATION
    entry["merge_policy_changed"] = False
    entry["updated_at"] = updated_at or utc_now()
    document["flags"][exact_name] = entry
    _save_flags(path, document)
    return {"flag": exact_name, "state": "kept", "entry": entry}


def kill_flag(
    path: str | Path,
    name: str,
    *,
    decision: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    exact_name = _validate_name(name)
    document = load_flags(path)
    current = document["flags"].get(exact_name, {})
    entry = {
        "enabled": False,
        "decision_reference": _validate_decision(decision),
        "expires_at": current.get("expires_at"),
        "classification": CLASSIFICATION,
        "merge_policy_changed": False,
        "killed_at": updated_at or utc_now(),
    }
    document["flags"][exact_name] = entry
    _save_flags(path, document)
    return {"flag": exact_name, "state": "killed", "entry": entry}


def sweep_expired(
    path: str | Path,
    issues_dir: str | Path,
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    if now.tzinfo is None:
        raise FlagError("sweep time must include a timezone")
    document = load_flags(path)
    issues: list[dict[str, Any]] = []
    for name, entry in sorted(document["flags"].items()):
        if entry.get("enabled") is not True:
            continue
        expires_at = _parse_expiry(entry.get("expires_at", ""))
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires > now:
            continue
        entry["enabled"] = False
        entry["killed_by_sweep"] = True
        entry["killed_at"] = now.isoformat()
        issue = {
            "schema_version": ISSUE_SCHEMA,
            "kind": "exposure-flag-cleanup",
            "flag": name,
            "decision_reference": entry.get("decision_reference", ""),
            "expired_at": expires_at,
            "swept_at": now.isoformat(),
            "action": "flag_disabled",
            "classification": CLASSIFICATION,
            "merge_policy_changed": False,
        }
        slug = re.sub(r"[^a-z0-9_-]+", "-", name)
        issue_path = Path(issues_dir).resolve() / f"cleanup-issue-{slug}-{int(now.timestamp())}.json"
        written = write_json_atomic(issue_path, issue)
        issue["path"] = str(written)
        write_json_atomic(issue_path, issue)
        issues.append(issue)
    if issues:
        _save_flags(path, document)
    return issues


def _print(value: dict[str, Any] | list[dict[str, Any]]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asdi-phase7-exposure")
    parser.add_argument("--flag-file", required=True, help="path to the local flag file")
    commands = parser.add_subparsers(dest="command", required=True)

    show = commands.add_parser("status")
    show.add_argument("--flag", default=None)

    for command in ("set", "keep"):
        subcommand = commands.add_parser(command)
        subcommand.add_argument("name")
        subcommand.add_argument("--decision", required=True)
        subcommand.add_argument("--expires-at", required=True)

    kill = commands.add_parser("kill")
    kill.add_argument("name")
    kill.add_argument("--decision", required=True)

    sweep = commands.add_parser("sweep")
    sweep.add_argument("--issues-dir", required=True)
    sweep.add_argument("--now", required=True, help="ISO-8601 sweep time with timezone")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "status":
            result: dict[str, Any] | list[dict[str, Any]] = status(arguments.flag_file, arguments.flag)
        elif arguments.command in {"set", "keep"}:
            action = set_flag if arguments.command == "set" else keep_flag
            result = action(
                arguments.flag_file,
                arguments.name,
                decision=arguments.decision,
                expires_at=arguments.expires_at,
            )
        elif arguments.command == "kill":
            result = kill_flag(
                arguments.flag_file, arguments.name, decision=arguments.decision
            )
        else:
            issues = sweep_expired(
                arguments.flag_file,
                arguments.issues_dir,
                now=datetime.fromisoformat(arguments.now.replace("Z", "+00:00")),
            )
            result = {"swept": len(issues), "issues": issues}
    except (FlagError, ApprovalError, OSError, ValueError) as error:
        print(f"exposure command refused: {error}", file=sys.stderr)
        return 2
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
