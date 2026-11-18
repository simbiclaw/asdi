"""Run-contract schema, defaults, provenance, and strict validation.

This module intentionally contains no launcher and performs no command execution.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


CONTRACT_SCHEMA_VERSION = "asdi.run-contract/v1"
AUTHORED_FIELDS = (
    "objective",
    "why",
    "constraints",
    "out_of_scope",
    "done_check",
)
PLATFORM_DEFAULT_FIELDS = (
    "boundaries",
    "guardrails",
    "output",
    "task_type",
)
PERMITTED_OVERRIDE_REASONS = (
    "owner_approved",
    "charter_approved",
    "safety_review",
)
DANGEROUS_DONE_CHECK_FLAGS = {
    "-c",
    "--command",
    "-e",
    "--eval",
    "--evaluate",
    "--execute",
}
SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


@dataclass(frozen=True)
class RunContractConfig:
    """Adjustable schema and provisional runtime defaults."""

    default_max_turns: int = 200
    default_max_spend_usd: float = 8.0
    default_wall_clock_seconds: int = 5400
    default_max_changed_lines: int = 400

    ceiling_max_turns: int = 1000
    ceiling_max_spend_usd: float = 100.0
    ceiling_wall_clock_seconds: int = 86_400
    ceiling_max_changed_lines: int = 5_000

    allowed_task_types: tuple[str, ...] = (
        "feature",
        "maintenance",
        "bugfix",
        "refactor",
        "documentation",
        "test",
        "spike",
        "experiment",
    )
    allowed_output_kinds: tuple[str, ...] = (
        "pull_request",
        "report",
        "artifact",
    )
    allowed_override_reasons: tuple[str, ...] = PERMITTED_OVERRIDE_REASONS
    allowed_done_check_executables: tuple[str, ...] = (
        "bun",
        "cargo",
        "deno",
        "go",
        "gradle",
        "make",
        "mvn",
        "node",
        "npm",
        "python",
        "python3",
        "pytest",
        "rake",
        "ruby",
    )


DEFAULT_CONFIG = RunContractConfig()


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    code: str
    message: str


class RunContractValidationError(ValueError):
    """Raised when a contract cannot be launched or normalized."""

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        rendered = "; ".join(f"{issue.path}: {issue.message}" for issue in self.issues)
        super().__init__(f"invalid run contract: {rendered}")


def build_run_contract(
    *,
    objective: str,
    why: str,
    constraints: list[str],
    out_of_scope: list[str],
    done_check: dict[str, Any],
    human_provided: list[str],
    lead_agent_authored: list[str],
    task_type: str = "feature",
    experiment_card_reference: str | None = None,
    config: RunContractConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Build a complete contract using platform defaults.

    The returned value is still passed through validate_run_contract before use;
    building only supplies defaults and provenance.
    """

    contract: dict[str, Any] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "task_type": task_type,
        "objective": objective,
        "why": why,
        "constraints": constraints,
        "out_of_scope": out_of_scope,
        "done_check": done_check,
        "boundaries": {
            "protected_paths": [
                "CODEOWNERS",
                "docs/asdi/decisions/**",
                "**/generated/",
                "**/*.generated.*",
            ],
            "max_changed_lines": config.default_max_changed_lines,
            "network": {"mode": "deny_all"},
            "production_access": False,
            "irreversible_actions": False,
        },
        "guardrails": {
            "max_turns": config.default_max_turns,
            "max_spend_usd": config.default_max_spend_usd,
            "wall_clock_seconds": config.default_wall_clock_seconds,
        },
        "output": {"kind": "report"},
        "provenance": {
            "human_provided": human_provided,
            "lead_agent_authored": lead_agent_authored,
            "platform_defaults": list(PLATFORM_DEFAULT_FIELDS),
        },
    }
    if experiment_card_reference is not None:
        contract["experiment_card_reference"] = experiment_card_reference
        contract["provenance"]["platform_defaults"].append(
            "experiment_card_reference"
        )
    return contract


def _issue(issues: list[ValidationIssue], path: str, code: str, message: str) -> None:
    issues.append(ValidationIssue(path=path, code=code, message=message))


def _non_empty_string(value: Any, *, max_length: int = 4_000) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= max_length
        and not any(ord(char) < 32 for char in value)
    )


def _string_list(
    issues: list[ValidationIssue],
    value: Any,
    path: str,
    *,
    allow_empty: bool,
    max_items: int = 100,
    max_item_length: int = 1_000,
) -> None:
    if not isinstance(value, list):
        _issue(issues, path, "type", "must be an array")
        return
    if not value and not allow_empty:
        _issue(issues, path, "empty", "must not be empty")
        return
    if len(value) > max_items:
        _issue(issues, path, "too_long", f"must contain at most {max_items} items")
        return
    for index, item in enumerate(value):
        item_path = f"{path}.{index}"
        if not _non_empty_string(item, max_length=max_item_length):
            _issue(
                issues,
                item_path,
                "type",
                "must be a non-empty printable string",
            )


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _positive_integer(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _safe_relative_path(value: Any) -> bool:
    if not _non_empty_string(value, max_length=1_000):
        return False
    path = Path(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and bool(path.parts)
        and not path.parts[0].startswith("-")
    )


def _safe_branch(value: Any) -> bool:
    return (
        _non_empty_string(value, max_length=250)
        and bool(SAFE_BRANCH_RE.fullmatch(value))
        and ".." not in value
        and not value.endswith("/")
        and not value.endswith(".lock")
        and "@{" not in value
    )


def _validate_done_check(
    issues: list[ValidationIssue],
    value: Any,
    config: RunContractConfig,
) -> None:
    path = "done_check"
    if not isinstance(value, dict):
        _issue(issues, path, "type", "must be an object")
        return
    unexpected = set(value) - {"description", "argv", "cwd", "timeout_seconds"}
    if unexpected:
        _issue(
            issues,
            path,
            "unknown_field",
            f"unsupported fields: {', '.join(sorted(unexpected))}",
        )
    if not _non_empty_string(value.get("description"), max_length=1_000):
        _issue(issues, f"{path}.description", "required", "must be a non-empty string")

    argv = value.get("argv")
    if not isinstance(argv, list) or not argv:
        _issue(issues, f"{path}.argv", "type", "must be a non-empty argv array")
        return
    if len(argv) > 32:
        _issue(issues, f"{path}.argv", "too_long", "must contain at most 32 items")
        return

    for index, argument in enumerate(argv):
        if not _non_empty_string(argument, max_length=1_000):
            _issue(
                issues,
                f"{path}.argv.{index}",
                "type",
                "must be a non-empty printable string",
            )
            continue
        if any(char in argument for char in ";|&`$()<>\n\r"):
            _issue(
                issues,
                f"{path}.argv.{index}",
                "unsafe_command",
                "shell-control or substitution characters are forbidden",
            )

    executable = argv[0]
    if isinstance(executable, str):
        basename = Path(executable).name
        if basename not in config.allowed_done_check_executables:
            _issue(
                issues,
                f"{path}.argv.0",
                "disallowed_executable",
                f"{basename!r} is not in the configured done-check allowlist",
            )
        if Path(executable).name in {"python", "python3", "node", "deno", "ruby"}:
            if set(argv[1:]) & DANGEROUS_DONE_CHECK_FLAGS:
                _issue(
                    issues,
                    path,
                    "unsafe_command",
                    "inline code-evaluation flags are forbidden",
                )

    cwd = value.get("cwd")
    if cwd is not None and not _safe_relative_path(cwd):
        _issue(issues, f"{path}.cwd", "unsafe_path", "must be a safe relative path")

    timeout = value.get("timeout_seconds")
    if timeout is not None and not _positive_integer(timeout):
        _issue(
            issues,
            f"{path}.timeout_seconds",
            "type",
            "must be a positive integer when present",
        )


def _validate_output(
    issues: list[ValidationIssue],
    value: Any,
    config: RunContractConfig,
) -> None:
    if not isinstance(value, dict):
        _issue(issues, "output", "type", "must be an object")
        return
    unexpected = set(value) - {"kind", "branch", "path"}
    if unexpected:
        _issue(
            issues,
            "output",
            "unknown_field",
            f"unsupported fields: {', '.join(sorted(unexpected))}",
        )
    kind = value.get("kind")
    if kind not in config.allowed_output_kinds:
        _issue(
            issues,
            "output.kind",
            "unsupported",
            f"must be one of: {', '.join(config.allowed_output_kinds)}",
        )
        return
    if kind == "pull_request" and not _safe_branch(value.get("branch")):
        _issue(issues, "output.branch", "required", "must be a safe Git branch name")
    if kind == "artifact" and not _safe_relative_path(value.get("path")):
        _issue(issues, "output.path", "required", "must be a safe relative path")


def _validate_guardrails(
    issues: list[ValidationIssue], value: Any, config: RunContractConfig
) -> None:
    if not isinstance(value, dict):
        _issue(issues, "guardrails", "type", "must be an object")
        return
    allowed = {"max_turns", "max_spend_usd", "wall_clock_seconds", "override_reason"}
    unexpected = set(value) - allowed
    if unexpected:
        _issue(
            issues,
            "guardrails",
            "unknown_field",
            f"unsupported fields: {', '.join(sorted(unexpected))}",
        )

    max_turns = value.get("max_turns")
    if not _positive_integer(max_turns):
        _issue(issues, "guardrails.max_turns", "invalid_budget", "must be a positive integer")
    elif max_turns > config.ceiling_max_turns:
        _issue(
            issues,
            "guardrails.max_turns",
            "over_ceiling",
            f"must not exceed configured ceiling {config.ceiling_max_turns}",
        )

    spend = value.get("max_spend_usd")
    if not _finite_number(spend) or spend < 0:
        _issue(
            issues,
            "guardrails.max_spend_usd",
            "invalid_budget",
            "must be a finite non-negative number",
        )
    elif spend > config.ceiling_max_spend_usd:
        _issue(
            issues,
            "guardrails.max_spend_usd",
            "over_ceiling",
            f"must not exceed configured ceiling {config.ceiling_max_spend_usd}",
        )

    wall_clock = value.get("wall_clock_seconds")
    if not _positive_integer(wall_clock):
        _issue(
            issues,
            "guardrails.wall_clock_seconds",
            "invalid_budget",
            "must be a positive integer",
        )
    elif wall_clock > config.ceiling_wall_clock_seconds:
        _issue(
            issues,
            "guardrails.wall_clock_seconds",
            "over_ceiling",
            f"must not exceed configured ceiling {config.ceiling_wall_clock_seconds}",
        )

    override_reason = value.get("override_reason")
    values = (max_turns, spend, wall_clock)
    defaults = (
        config.default_max_turns,
        config.default_max_spend_usd,
        config.default_wall_clock_seconds,
    )
    raises_default = all(
        isinstance(item, (int, float)) and not isinstance(item, bool)
        for item in values
    ) and any(current > default for current, default in zip(values, defaults))
    if raises_default:
        if override_reason not in config.allowed_override_reasons:
            _issue(
                issues,
                "guardrails.override_reason",
                "unapproved_override",
                "raising a default requires a permitted override reason",
            )
    elif override_reason is not None and override_reason not in config.allowed_override_reasons:
        _issue(
            issues,
            "guardrails.override_reason",
            "unsupported",
            f"must be one of: {', '.join(config.allowed_override_reasons)}",
        )


def _validate_boundaries(
    issues: list[ValidationIssue], value: Any, config: RunContractConfig
) -> None:
    if not isinstance(value, dict):
        _issue(issues, "boundaries", "type", "must be an object")
        return
    allowed = {
        "protected_paths",
        "max_changed_lines",
        "network",
        "production_access",
        "irreversible_actions",
        "override_reason",
    }
    unexpected = set(value) - allowed
    if unexpected:
        _issue(
            issues,
            "boundaries",
            "unknown_field",
            f"unsupported fields: {', '.join(sorted(unexpected))}",
        )

    _string_list(
        issues,
        value.get("protected_paths"),
        "boundaries.protected_paths",
        allow_empty=False,
        max_item_length=500,
    )
    changed_lines = value.get("max_changed_lines")
    if not _positive_integer(changed_lines):
        _issue(
            issues,
            "boundaries.max_changed_lines",
            "invalid_limit",
            "must be a positive integer",
        )
    elif changed_lines > config.ceiling_max_changed_lines:
        _issue(
            issues,
            "boundaries.max_changed_lines",
            "over_ceiling",
            f"must not exceed configured ceiling {config.ceiling_max_changed_lines}",
        )

    if value.get("production_access") is not False:
        _issue(
            issues,
            "boundaries.production_access",
            "forbidden",
            "must be false; production access is not authorized by a run contract",
        )
    if value.get("irreversible_actions") is not False:
        _issue(
            issues,
            "boundaries.irreversible_actions",
            "forbidden",
            "must be false; irreversible actions require an explicit human gate",
        )

    network = value.get("network")
    if not isinstance(network, dict):
        _issue(issues, "boundaries.network", "type", "must be an object")
    else:
        allowed_network_fields = {
            "mode",
            "allowlist",
            "override_reason",
            "override_reference",
            "scope",
        }
        unexpected_network = set(network) - allowed_network_fields
        if unexpected_network:
            _issue(
                issues,
                "boundaries.network",
                "unknown_field",
                f"unsupported fields: {', '.join(sorted(unexpected_network))}",
            )
        mode = network.get("mode")
        allowlist = network.get("allowlist")
        if mode == "deny_all":
            if allowlist not in (None, []):
                _issue(
                    issues,
                    "boundaries.network.allowlist",
                    "conflict",
                    "must be absent or empty when network mode is deny_all",
                )
        elif mode == "allowlist":
            _string_list(
                issues,
                allowlist,
                "boundaries.network.allowlist",
                allow_empty=False,
                max_items=64,
                max_item_length=253,
            )
            if isinstance(allowlist, list):
                for index, endpoint in enumerate(allowlist):
                    if isinstance(endpoint, str) and (
                        endpoint == "*" or any(char in endpoint for char in " /\\")
                    ):
                        _issue(
                            issues,
                            f"boundaries.network.allowlist.{index}",
                            "unsafe_endpoint",
                            "must be a specific host or host:port",
                        )
        elif mode == "development_open":
            if allowlist not in (None, []):
                _issue(
                    issues,
                    "boundaries.network.allowlist",
                    "conflict",
                    "must be absent or empty when network mode is development_open",
                )
            if value.get("production_access") is not False:
                _issue(
                    issues,
                    "boundaries.production_access",
                    "forbidden",
                    "development_open does not authorize production access",
                )
            network_override_reason = network.get("override_reason")
            network_override_reference = network.get("override_reference")
            network_scope = network.get("scope")
            if network_override_reason != "owner_approved":
                _issue(
                    issues,
                    "boundaries.network.override_reason",
                    "unapproved_override",
                    "development_open requires owner_approved",
                )
            if not _non_empty_string(network_override_reference, max_length=200):
                _issue(
                    issues,
                    "boundaries.network.override_reference",
                    "required",
                    "must reference the owner's explicit development decision",
                )
            if network_scope != "development_only":
                _issue(
                    issues,
                    "boundaries.network.scope",
                    "forbidden",
                    "development_open is limited to development_only",
                )
        else:
            _issue(
                issues,
                "boundaries.network.mode",
                "unsupported",
                "must be deny_all, allowlist, or development_open",
            )

    override_reason = value.get("override_reason")
    raises_changed_line_default = (
        isinstance(changed_lines, int)
        and not isinstance(changed_lines, bool)
        and changed_lines > config.default_max_changed_lines
    )
    if raises_changed_line_default and override_reason not in config.allowed_override_reasons:
        _issue(
            issues,
            "boundaries.override_reason",
            "unapproved_override",
            "raising the diff default requires a permitted override reason",
        )
    elif override_reason is not None and override_reason not in config.allowed_override_reasons:
        _issue(
            issues,
            "boundaries.override_reason",
            "unsupported",
            f"must be one of: {', '.join(config.allowed_override_reasons)}",
        )


def _validate_provenance(
    issues: list[ValidationIssue], value: Any, *, has_experiment_reference: bool
) -> None:
    if not isinstance(value, dict):
        _issue(issues, "provenance", "type", "must be an object")
        return
    required = {"human_provided", "lead_agent_authored", "platform_defaults"}
    unexpected = set(value) - required
    missing = required - set(value)
    if unexpected:
        _issue(
            issues,
            "provenance",
            "unknown_field",
            f"unsupported fields: {', '.join(sorted(unexpected))}",
        )
    if missing:
        _issue(
            issues,
            "provenance",
            "missing",
            f"missing fields: {', '.join(sorted(missing))}",
        )
        return

    field_lists: dict[str, list[Any]] = {}
    for source in required:
        items = value[source]
        _string_list(
            issues,
            items,
            f"provenance.{source}",
            allow_empty=source != "platform_defaults",
            max_items=32,
            max_item_length=100,
        )
        if isinstance(items, list):
            field_lists[source] = items

    if len(field_lists) != len(required):
        return
    human = set(field_lists["human_provided"])
    lead = set(field_lists["lead_agent_authored"])
    for source, items in (("human_provided", field_lists["human_provided"]), (
        "lead_agent_authored", field_lists["lead_agent_authored"]
    )):
        if len(items) != len(set(items)):
            _issue(
                issues,
                f"provenance.{source}",
                "duplicate",
                "must not contain duplicate fields",
            )
        unknown_fields = set(items) - set(AUTHORED_FIELDS)
        if unknown_fields:
            _issue(
                issues,
                f"provenance.{source}",
                "unknown_field",
                f"unsupported authored fields: {', '.join(sorted(unknown_fields))}",
            )
    overlap = human & lead
    if overlap:
        _issue(
            issues,
            "provenance",
            "conflict",
            f"fields have multiple sources: {', '.join(sorted(overlap))}",
        )
    if human | lead != set(AUTHORED_FIELDS):
        _issue(
            issues,
            "provenance",
            "incomplete",
            "human and lead-agent provenance must partition the five authored fields",
        )
    expected_platform = set(PLATFORM_DEFAULT_FIELDS)
    if has_experiment_reference:
        expected_platform.add("experiment_card_reference")
    provided_platform = set(field_lists["platform_defaults"])
    if len(field_lists["platform_defaults"]) != len(provided_platform):
        _issue(
            issues,
            "provenance.platform_defaults",
            "duplicate",
            "must not contain duplicate fields",
        )
    unexpected_platform = provided_platform - expected_platform
    if unexpected_platform:
        _issue(
            issues,
            "provenance.platform_defaults",
            "unknown_field",
            f"unsupported platform fields: {', '.join(sorted(unexpected_platform))}",
        )
    missing_platform = expected_platform - provided_platform
    if missing_platform:
        _issue(
            issues,
            "provenance.platform_defaults",
            "incomplete",
            f"missing platform fields: {', '.join(sorted(missing_platform))}",
        )


def validate_run_contract(
    value: Any, config: RunContractConfig = DEFAULT_CONFIG
) -> dict[str, Any]:
    """Validate a contract and return a defensive copy when valid."""

    issues: list[ValidationIssue] = []
    if not isinstance(value, dict):
        raise RunContractValidationError(
            [ValidationIssue("$", "type", "run contract must be an object")]
        )

    allowed_top_level = {
        "schema_version",
        "task_type",
        *AUTHORED_FIELDS,
        "boundaries",
        "guardrails",
        "output",
        "experiment_card_reference",
        "provenance",
    }
    unexpected = set(value) - allowed_top_level
    missing = allowed_top_level - set(value) - {"experiment_card_reference"}
    if unexpected:
        _issue(
            issues,
            "$",
            "unknown_field",
            f"unsupported fields: {', '.join(sorted(unexpected))}",
        )
    if missing:
        _issue(
            issues,
            "$",
            "missing",
            f"missing fields: {', '.join(sorted(missing))}",
        )
    if value.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        _issue(
            issues,
            "schema_version",
            "unsupported",
            f"must be {CONTRACT_SCHEMA_VERSION!r}",
        )

    task_type = value.get("task_type")
    if task_type not in config.allowed_task_types:
        _issue(
            issues,
            "task_type",
            "unsupported",
            f"must be one of: {', '.join(config.allowed_task_types)}",
        )

    if not _non_empty_string(value.get("objective"), max_length=1_000):
        _issue(issues, "objective", "required", "must be a non-empty string")
    if not _non_empty_string(value.get("why"), max_length=4_000):
        _issue(issues, "why", "required", "must be a non-empty string")
    _string_list(
        issues, value.get("constraints"), "constraints", allow_empty=True
    )
    _string_list(
        issues, value.get("out_of_scope"), "out_of_scope", allow_empty=True
    )
    _validate_done_check(issues, value.get("done_check"), config)
    _validate_boundaries(issues, value.get("boundaries"), config)
    _validate_guardrails(issues, value.get("guardrails"), config)
    _validate_output(issues, value.get("output"), config)

    experiment_reference = value.get("experiment_card_reference")
    if experiment_reference is not None and not _non_empty_string(
        experiment_reference, max_length=200
    ):
        _issue(
            issues,
            "experiment_card_reference",
            "type",
            "must be a non-empty string when present",
        )

    _validate_provenance(
        issues,
        value.get("provenance"),
        has_experiment_reference="experiment_card_reference" in value,
    )

    if issues:
        raise RunContractValidationError(issues)
    return json.loads(json.dumps(value))


def validate_file(
    path: str | Path, config: RunContractConfig = DEFAULT_CONFIG
) -> dict[str, Any]:
    """Load and validate one JSON contract file."""

    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    return validate_run_contract(value, config=config)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an ASDI run contract")
    parser.add_argument("command", choices=["validate"])
    parser.add_argument("contract", help="path to a run-contract JSON file")
    args = parser.parse_args(argv)
    try:
        validate_file(args.contract)
    except (OSError, json.JSONDecodeError, RunContractValidationError) as error:
        print(f"FAIL: {error}", flush=True)
        return 2
    print("PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
