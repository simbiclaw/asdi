"""Config loading with the standard library only (ADR-0005).

``config/*.yaml`` in this repo use a small subset of YAML: nested mappings by
two-space indentation, scalar values, and ``- item`` lists. This reader handles
exactly that subset and refuses anything else rather than guessing.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _scalar(text: str) -> Any:
    text = text.strip()
    if text in ("true", "false"):
        return text == "true"
    if text in ("null", "~", ""):
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        return text


def load_simple_yaml(path: str | Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = Path(path).read_text().splitlines()
    for number, raw in enumerate(lines, start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        text = raw.strip()
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if text.startswith("- "):
            if not isinstance(parent, list):
                raise ValueError(f"{path}:{number}: list item outside a list")
            parent.append(_scalar(text[2:]))
            continue
        key, sep, value = text.partition(":")
        if not sep or not isinstance(parent, dict):
            raise ValueError(f"{path}:{number}: unsupported YAML")
        if value.strip():
            parent[key.strip()] = _scalar(value)
            continue
        # Empty value: a nested mapping or list follows; peek at the next line.
        following = next((l for l in lines[number:] if l.strip() and not l.lstrip().startswith("#")), "")
        child: Any = [] if following.strip().startswith("- ") else {}
        parent[key.strip()] = child
        stack.append((indent, child))
    return root


@dataclass(frozen=True)
class ReviewerConfig:
    repo: str
    inbox_path: Path
    evidence_root: Path
    notifications_log: Path
    status_context: str
    status_identity: str
    token_env: str
    evidence_base_url: str | None
    model: dict[str, Any] | None
    builder_families: list[str]
    max_diff_chars: int
    ignore_prs: tuple[int, ...]
    ignore_created_before: str | None
    lease_seconds: int
    max_attempts: int
    poll_interval_seconds: int
    stale_after_seconds: int
    may_post_status: bool
    trusted_reviewers: list[str] = dataclasses.field(default_factory=list)
    include_prs: tuple[int, ...] = ()


def load_reviewer_config(path: str | Path | None = None) -> ReviewerConfig:
    review = json.loads(Path(path or ROOT / "config" / "review.json").read_text())
    defaults = load_simple_yaml(ROOT / "config" / "defaults.yaml")
    identities = load_simple_yaml(ROOT / "config" / "identities.yaml")
    identity = review["status_identity"]
    rights = identities.get("identities", {}).get(identity, {})
    passes = [p for p in review.get("passes", []) if p.get("pass") == "review"]

    def local(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else ROOT / candidate

    return ReviewerConfig(
        repo=review["repo"],
        inbox_path=local(review["inbox_path"]),
        evidence_root=local(review["evidence_root"]),
        notifications_log=local(review["notifications_log"]),
        status_context=review["status_context"],
        status_identity=identity,
        token_env=review["token_env"],
        evidence_base_url=review.get("evidence_base_url"),
        model=passes[0].get("model") if passes else None,
        builder_families=list(review["builder_families"]),
        max_diff_chars=int(review["max_diff_chars"]),
        ignore_prs=tuple(int(n) for n in review.get("ignore_prs", [])),
        ignore_created_before=review.get("ignore_prs_created_before"),
        lease_seconds=int(review["lease_seconds"]),
        max_attempts=int(review["max_attempts"]),
        poll_interval_seconds=int(defaults["poller_interval_seconds"]),
        stale_after_seconds=int(defaults["poller_stale_after_seconds"]),
        may_post_status=rights.get("may_post_status") is True and rights.get("may_merge") is False,
        trusted_reviewers=list(review.get("trusted_reviewers", [])),
        include_prs=tuple(int(n) for n in review.get("include_prs", [])),
    )
