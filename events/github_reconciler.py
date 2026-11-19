#!/usr/bin/env python3
"""Read-only GitHub reconciliation for the passive local event journal.

This module polls current repository state with an explicit, shell-free ``gh``
command.  It emits only normalized PR-head and ``main``-commit discovery
events.  It does not post statuses, execute workflows, accept webhooks, merge,
run agents, or treat GitHub review text as trusted instructions.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .journal import EventJournal, atomic_json, utc_now


FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
FORBIDDEN_COMMAND_MARKERS = ("api_key", "authorization", "password", "secret", "token")


@dataclass(frozen=True)
class GitHubCommand:
    """Bounded execution boundary for one read-only GitHub CLI invocation."""

    argv: tuple[str, ...]
    timeout_seconds: float = 20.0
    environment: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.argv or not Path(self.argv[0]).is_absolute():
            raise ValueError("GitHub command executable must be absolute")
        if self.timeout_seconds <= 0:
            raise ValueError("GitHub command timeout must be positive")
        if any(not isinstance(token, str) or not token for token in self.argv):
            raise ValueError("GitHub command arguments must be non-empty strings")
        if any(
            any(ord(char) < 32 for char in token) for token in self.argv
        ):
            raise ValueError("GitHub command arguments must be printable")
        if any(
            marker in token.lower()
            for token in self.argv
            for marker in FORBIDDEN_COMMAND_MARKERS
        ):
            raise ValueError("GitHub command may not contain credential-like names")

    def run(self) -> tuple[int, str, str, bool]:
        timed_out = False
        stdout = ""
        stderr = ""
        try:
            completed = subprocess.run(
                list(self.argv),
                env=self.environment or {},
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            return completed.returncode, completed.stdout, completed.stderr, False
        except subprocess.TimeoutExpired as error:
            timed_out = True
            stdout = error.stdout if isinstance(error.stdout, str) else ""
            stderr = error.stderr if isinstance(error.stderr, str) else ""
            return 124, stdout, stderr, True


def default_github_environment(*, proxy_url: str | None = None) -> dict[str, str]:
    """Return a minimal environment without inherited credentials."""

    environment = {
        "HOME": str(Path.home()),
        "LANG": "C.UTF-8",
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "NO_PROXY": "127.0.0.1,localhost",
    }
    if proxy_url:
        environment.update(
            {
                "HTTP_PROXY": proxy_url,
                "HTTPS_PROXY": proxy_url,
                "http_proxy": proxy_url,
                "https_proxy": proxy_url,
            }
        )
    return environment


class GitHubReconciler:
    """Append current-state events once per repository fact."""

    def __init__(
        self,
        *,
        journal: EventJournal,
        state_path: str | Path,
        repository: str,
        base_ref: str,
        pr_command: GitHubCommand,
        main_command: GitHubCommand,
    ) -> None:
        if not REPOSITORY.fullmatch(repository):
            raise ValueError("repository must be owner/repo")
        if not base_ref or not re.fullmatch(r"[A-Za-z0-9._/-]+", base_ref):
            raise ValueError("invalid base ref")
        self.journal = journal
        self.state_path = Path(state_path).resolve()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.repository = repository
        self.base_ref = base_ref
        self.pr_command = pr_command
        self.main_command = main_command

    def reconcile(self) -> dict[str, Any]:
        pr_result, pr_json = self._run_json(self.pr_command, expected="array")
        main_result, main_json = self._run_json(self.main_command, expected="object")
        if not pr_result["ok"] or not main_result["ok"]:
            failures = [
                *pr_result.get("failures", []),
                *main_result.get("failures", []),
            ]
            self._save_health(False, failures, [pr_result, main_result])
            raise RuntimeError("GitHub reconciliation failed: " + "; ".join(failures))

        appended: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        duplicates = 0
        seen = self._journal_signatures()

        for index, item in enumerate(pr_json if isinstance(pr_json, list) else []):
            normalized = self._normalize_pull_request(item)
            if normalized.get("failures"):
                rejected.append(
                    {
                        "source": f"pull_request[{index}]",
                        "failures": normalized["failures"],
                    }
                )
                continue
            payload = {
                "pr_number": normalized["pr_number"],
                "head_sha": normalized["head_sha"],
                "base_ref": normalized["base_ref"],
                "changed_paths": normalized["changed_paths"],
            }
            signature = self.pull_request_signature(payload)
            if signature in seen:
                duplicates += 1
                continue
            event = self.journal.append(
                event_type="github.pull_request",
                payload=payload,
            )
            appended.append(event)
            seen.add(signature)

        main_sha = main_json.get("sha") if isinstance(main_json, dict) else None
        if isinstance(main_sha, str) and FULL_SHA.fullmatch(main_sha):
            payload = {"branch": self.base_ref, "commit": main_sha}
            signature = self.main_signature(payload)
            if signature not in seen:
                event = self.journal.append(
                    event_type="github.push",
                    payload=payload,
                )
                appended.append(event)
                seen.add(signature)
            else:
                duplicates += 1
        else:
            rejected.append(
                {
                    "source": "main",
                    "failures": ["main command did not return a 40-character SHA"],
                }
            )

        result = {
            "schema_version": "asdi.github-reconciliation/v1",
            "repository": self.repository,
            "base_ref": self.base_ref,
            "read_only": True,
            "webhook": False,
            "appended_count": len(appended),
            "events": appended,
            "duplicate_count": duplicates,
            "rejected": rejected,
            "commands": [pr_result, main_result],
            "reconciled_at": utc_now(),
        }
        self._save_health(True, [])
        atomic_json(
            self.state_path.with_name(self.state_path.name + ".last.json"),
            result,
        )
        return result

    def _run_json(
        self,
        command: GitHubCommand,
        *,
        expected: str,
    ) -> tuple[dict[str, Any], Any]:
        exit_code, stdout, stderr, timed_out = command.run()
        result = {
            "argv": list(command.argv),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stderr_tail": stderr[-2000:],
            "stdout_tail": "",
            "ok": False,
        }
        parsed: Any = None
        failures: list[str] = []
        if timed_out:
            failures.append("GitHub command timed out")
        elif exit_code != 0:
            failures.append(f"GitHub command exited {exit_code}")
        if not failures:
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError as error:
                failures.append(f"GitHub command returned invalid JSON: {error}")
        if not failures:
            if expected == "array" and not isinstance(parsed, list):
                failures.append("GitHub command did not return an array")
            if expected == "object" and not isinstance(parsed, dict):
                failures.append("GitHub command did not return an object")
        result["failures"] = failures
        if failures:
            result["stdout_tail"] = stdout[-2000:]
        result["ok"] = not failures
        return result, parsed

    def _normalize_pull_request(self, item: Any) -> dict[str, Any]:
        failures: list[str] = []
        if not isinstance(item, dict):
            return {"failures": ["pull request is not an object"]}
        number = item.get("number")
        head_sha = item.get("headRefOid")
        base_ref = item.get("baseRefName")
        files = item.get("files")
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            failures.append("number must be a positive integer")
        if not isinstance(head_sha, str) or not FULL_SHA.fullmatch(head_sha):
            failures.append("headRefOid must be a 40-character lowercase SHA")
        if base_ref != self.base_ref:
            failures.append(f"unexpected base ref {base_ref!r}")
        paths: list[str] = []
        if not isinstance(files, list):
            failures.append("files must be an array")
        else:
            for file_item in files:
                path = file_item.get("path") if isinstance(file_item, dict) else None
                if not isinstance(path, str) or not path:
                    failures.append("changed file has no path")
                else:
                    paths.append(path)
        if not paths:
            failures.append("pull request has no changed paths")
        return {
            "failures": sorted(set(failures)),
            "pr_number": number,
            "head_sha": head_sha,
            "base_ref": base_ref,
            "changed_paths": sorted(set(paths)),
        }

    def _journal_signatures(self) -> set[str]:
        signatures: set[str] = set()
        for event in self.journal.load():
            event_type = event.get("event_type")
            payload = event.get("payload")
            if event_type == "github.pull_request" and isinstance(payload, dict):
                signatures.add(self.pull_request_signature(payload))
            elif event_type == "github.push" and isinstance(payload, dict):
                signatures.add(self.main_signature(payload))
        return signatures

    @staticmethod
    def pull_request_signature(payload: dict[str, Any]) -> str:
        paths = ",".join(sorted(str(path) for path in payload.get("changed_paths", [])))
        return (
            f"pr:{payload.get('pr_number')}:{payload.get('head_sha')}:"
            f"{payload.get('base_ref')}:{paths}"
        )

    @staticmethod
    def main_signature(payload: dict[str, Any]) -> str:
        return f"main:{payload.get('branch')}:{payload.get('commit')}"

    def _save_health(
        self,
        healthy: bool,
        failures: list[str],
        command_results: list[dict[str, Any]] | None = None,
    ) -> None:
        state = {
            "schema_version": "asdi.github-reconciler-health/v1",
            "repository": self.repository,
            "healthy": healthy,
            "alert": None if healthy else "github_reconciliation_failed",
            "failures": failures,
            "updated_at": utc_now(),
        }
        if command_results is not None:
            state["command_results"] = command_results
        atomic_json(self.state_path, state)
