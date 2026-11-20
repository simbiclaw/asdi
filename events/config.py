"""Load operational defaults from the authoritative config files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "defaults.yaml"
PILOT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "pilot.yaml"


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return float(value)


@dataclass(frozen=True)
class GuardrailDefaults:
    turns: int
    spend_usd: float
    minutes: int
    tokens: int | None


@dataclass(frozen=True)
class PilotSelection:
    active: str
    product_root: Path
    run_image: str


@dataclass(frozen=True)
class OperationalDefaults:
    work_in_progress_limit: int
    diff_budget_lines: int
    evidence_retention_days_after_pr_close: int
    experiment_expiry_days: int
    experiment_wip_limit: int
    production_verification_hours: int
    repair_attempts: int
    poller_interval_seconds: int
    poller_stale_after_seconds: int
    review_timeout_seconds: float
    verifier_timeout_seconds: float
    github_reconciler_timeout_seconds: float
    remediation_timeout_seconds: float
    readonly_audit_timeout_seconds: float
    guardrails: GuardrailDefaults


def load_pilot_config(path: str | Path = PILOT_CONFIG_PATH) -> PilotSelection:
    value = yaml.safe_load(Path(path).read_text())
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("pilot config must be version 1")
    active = value.get("active")
    if not isinstance(active, str) or not active:
        raise ValueError("pilot config has no active pilot")
    pilots = value.get("pilots")
    if not isinstance(pilots, dict):
        raise ValueError("pilot config pilots must be an object")
    selected = pilots.get(active)
    if not isinstance(selected, dict):
        raise ValueError(f"active pilot {active!r} has no configuration")
    product_root = selected.get("product_root")
    run_image = selected.get("run_image")
    if not isinstance(product_root, str) or not product_root:
        raise ValueError("active pilot product_root is required")
    if not isinstance(run_image, str) or not run_image:
        raise ValueError("active pilot run_image is required")
    return PilotSelection(
        active=active,
        product_root=PILOT_CONFIG_PATH.parents[1] / product_root,
        run_image=run_image,
    )


def load_defaults(path: str | Path) -> dict[str, Any]:
    value = yaml.safe_load(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("defaults config must be an object")
    return dict(value)


def load_operational_defaults(
    path: str | Path = DEFAULT_CONFIG_PATH,
) -> OperationalDefaults:
    value = load_defaults(path)
    guardrails = value.get("guardrails")
    if not isinstance(guardrails, dict):
        raise ValueError("guardrails must be an object")
    tokens = guardrails.get("tokens")
    if tokens is not None:
        tokens = _positive_int(tokens, "guardrails.tokens")
    return OperationalDefaults(
        work_in_progress_limit=_positive_int(
            value.get("work_in_progress_limit"), "work_in_progress_limit"
        ),
        diff_budget_lines=_positive_int(
            value.get("diff_budget_lines"), "diff_budget_lines"
        ),
        evidence_retention_days_after_pr_close=_positive_int(
            value.get("evidence_retention_days_after_pr_close"),
            "evidence_retention_days_after_pr_close",
        ),
        experiment_expiry_days=_positive_int(
            value.get("experiment_expiry_days"), "experiment_expiry_days"
        ),
        experiment_wip_limit=_positive_int(
            value.get("experiment_wip_limit"), "experiment_wip_limit"
        ),
        production_verification_hours=_positive_int(
            value.get("production_verification_hours"),
            "production_verification_hours",
        ),
        repair_attempts=_positive_int(value.get("repair_attempts"), "repair_attempts"),
        poller_interval_seconds=_positive_int(
            value.get("poller_interval_seconds"), "poller_interval_seconds"
        ),
        poller_stale_after_seconds=_positive_int(
            value.get("poller_stale_after_seconds"), "poller_stale_after_seconds"
        ),
        review_timeout_seconds=_positive_float(
            value.get("review_timeout_seconds"), "review_timeout_seconds"
        ),
        verifier_timeout_seconds=_positive_float(
            value.get("verifier_timeout_seconds"), "verifier_timeout_seconds"
        ),
        github_reconciler_timeout_seconds=_positive_float(
            value.get("github_reconciler_timeout_seconds"),
            "github_reconciler_timeout_seconds",
        ),
        remediation_timeout_seconds=_positive_float(
            value.get("remediation_timeout_seconds"),
            "remediation_timeout_seconds",
        ),
        readonly_audit_timeout_seconds=_positive_float(
            value.get("readonly_audit_timeout_seconds"),
            "readonly_audit_timeout_seconds",
        ),
        guardrails=GuardrailDefaults(
            turns=_positive_int(guardrails.get("turns"), "guardrails.turns"),
            spend_usd=_positive_float(
                guardrails.get("spend_usd"), "guardrails.spend_usd"
            ),
            minutes=_positive_int(guardrails.get("minutes"), "guardrails.minutes"),
            tokens=tokens,
        ),
    )
