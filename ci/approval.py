"""Fail-closed loading of durable REV K deployment approval evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
OPS_REGISTRY_REF = re.compile(r"^[a-z0-9][a-z0-9.-]*(?::[0-9]+)?/[a-z0-9._/-]+$")


class ApprovalError(ValueError):
    """Raised when a commit lacks valid, current, passing main evidence."""


def validate_commit(commit: Any) -> str:
    if not isinstance(commit, str) or not FULL_SHA.fullmatch(commit):
        raise ApprovalError("commit must be an exact 40-character lowercase SHA")
    return commit


def validate_digest(digest: Any) -> str:
    if not isinstance(digest, str) or not IMAGE_DIGEST.fullmatch(digest):
        raise ApprovalError("image digest must be sha256 followed by 64 lowercase hex digits")
    return digest


def validate_ops_registry(registry: Any) -> str:
    if not isinstance(registry, str) or not OPS_REGISTRY_REF.fullmatch(registry):
        raise ApprovalError(
            "registry must be an ops registry repository reference without a URL scheme"
        )
    if "agent" in registry or "staging" in registry:
        raise ApprovalError("registry must be the ops registry, not an agent or staging namespace")
    return registry


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write_json_atomic(path: str | Path, value: dict[str, Any]) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


def load_deployment_approval(
    path: str | Path,
    commit: Any,
    *,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Return normalized approval evidence or fail closed.

    Accepted documents are the durable post-merge deployment decisions emitted
    by the Phase 4 workflow, including the enclosing pipeline record.  A
    decision for another commit, a failed result, or a required revert is
    never sufficient.
    """

    exact_commit = validate_commit(commit)
    decision_path = Path(path).resolve()
    if not decision_path.is_file():
        raise ApprovalError(f"deployment decision file is missing: {decision_path}")
    raw = decision_path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ApprovalError(f"deployment decision file is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise ApprovalError("deployment decision file must contain a JSON object")

    decision = document.get("deployment")
    if not isinstance(decision, dict):
        decision = document
    if decision.get("commit") != exact_commit:
        raise ApprovalError("deployment decision is stale: it names a different commit")

    post_merge = decision.get("post_merge")
    if not isinstance(post_merge, dict):
        post_merge = document.get("post_merge") if isinstance(document.get("post_merge"), dict) else None
        if post_merge is None and isinstance(document.get("result"), dict):
            post_merge = document["result"]
    if not isinstance(post_merge, dict):
        raise ApprovalError("deployment decision has no post-merge result")
    if post_merge.get("commit") != exact_commit:
        raise ApprovalError("post-merge result is stale: it names a different commit")
    if post_merge.get("passed") is not True:
        raise ApprovalError("post-merge result did not pass")
    if post_merge.get("deployment_eligible") is not True:
        raise ApprovalError("post-merge result does not permit deployment")
    if post_merge.get("failures") != []:
        raise ApprovalError("post-merge result records failures")
    auto_revert = post_merge.get("auto_revert")
    if isinstance(auto_revert, dict) and auto_revert.get("required") is True:
        raise ApprovalError("post-merge result requires auto-revert")
    if decision.get("eligible") is not True:
        raise ApprovalError("deployment decision is not eligible")

    branch = document.get("branch", post_merge.get("branch"))
    if branch is not None and branch != "main":
        raise ApprovalError("approval evidence is not bound to main")
    source = document.get("source", post_merge.get("source"))
    if source is not None and source != "main":
        raise ApprovalError("approval evidence has a non-main source")

    if max_age_seconds is not None:
        if not isinstance(max_age_seconds, int) or max_age_seconds < 0:
            raise ApprovalError("max_age_seconds must be a non-negative integer")
        recorded = next(
            (
                parsed
                for key in ("recorded_at", "updated_at", "created_at", "verified_at")
                if (parsed := _parse_timestamp(document.get(key, post_merge.get(key)))) is not None
            ),
            None,
        )
        if recorded is None:
            raise ApprovalError("approval evidence has no parseable timestamp for a freshness check")
        age = time.time() - recorded
        if age < -60:
            raise ApprovalError("approval evidence timestamp is in the future")
        if age > max_age_seconds:
            raise ApprovalError(
                f"approval evidence is stale: older than {max_age_seconds} seconds"
            )

    return {
        "schema_version": "asdi.phase7-approval/v1",
        "path": str(decision_path),
        "evidence_sha256": sha256_bytes(raw),
        "document_schema": document.get("schema_version"),
        "commit": exact_commit,
        "source": "main",
        "post_merge": post_merge,
    }
