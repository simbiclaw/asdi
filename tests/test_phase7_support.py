"""Shared fakes for the REV K Phase 7 builder-side tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ci.approval import write_json_atomic
from ci.docker import CommandResult

COMMIT = "a" * 40
PRIOR_COMMIT = "b" * 40
DIGEST = "sha256:" + "1" * 64
PRIOR_DIGEST = "sha256:" + "2" * 64
REGISTRY = "ops-registry.local/toy-notes"


def write_decision(
    path: str | Path,
    commit: str,
    *,
    passed: bool = True,
    eligible: bool = True,
    branch: str = "main",
    source: str = "main",
    failures: list[str] | None = None,
    auto_revert: bool = False,
) -> Path:
    post_merge: dict[str, Any] = {
        "commit": commit,
        "passed": passed,
        "failures": failures or [],
        "deployment_eligible": eligible,
    }
    if auto_revert:
        post_merge["auto_revert"] = {"required": True, "reason": "test"}
    document = {
        "schema_version": "asdi.main-verification-pipeline/v1",
        "commit": commit,
        "branch": branch,
        "source": source,
        "recorded_at": "2026-11-20T00:00:00+00:00",
        "post_merge": post_merge,
        "deployment": {
            "commit": commit,
            "eligible": eligible and passed and not auto_revert,
            "post_merge": post_merge,
        },
        "deployed": False,
    }
    return write_json_atomic(path, document)


@dataclass
class FakeDockerRunner:
    digest: str = DIGEST
    image_archive: bytes = b"fake-oci-archive"
    commands: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, args: Sequence[str], *, check: bool = True) -> CommandResult:
        command = tuple(str(arg) for arg in args)
        self.commands.append(command)
        if command[:2] == ("buildx", "build"):
            return CommandResult(command, 0, "built\n", "")
        if command[:3] == ("buildx", "imagetools", "inspect"):
            return CommandResult(command, 0, f"{self.digest}\n", "")
        if command[0] == "pull":
            return CommandResult(command, 0, "pulled\n", "")
        if command[:2] == ("image", "save"):
            output = command[command.index("--output") + 1]
            Path(output).write_bytes(self.image_archive)
            return CommandResult(command, 0, "", "")
        if command[0] == "run":
            return CommandResult(command, 0, "fake-container-id\n", "")
        if command[0] == "rm":
            return CommandResult(command, 0, "fake-container-id\n", "")
        if command[0] == "version":
            return CommandResult(command, 0, "fake docker\n", "")
        raise AssertionError(f"unexpected fake Docker command: {command}")


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
