#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from events.github_reconciler import (
    GitHubCommand,
    GitHubReconciler,
    default_github_environment,
)
from events.journal import EventJournal


HEAD = "a" * 40
MAIN = "b" * 40
PR_OUTPUT = json.dumps(
    [
        {
            "number": 7,
            "headRefOid": HEAD,
            "baseRefName": "main",
            "files": [
                {"path": "src/feature.py"},
                {"path": "src/feature.py"},
            ],
        }
    ]
)
MAIN_OUTPUT = json.dumps({"sha": MAIN})


class GitHubReconcilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.journal = EventJournal(self.root / "journal")
        self.command_path = self.root / "fake-gh"
        self.command_path.write_text(
            "#!/bin/sh\n"
            "cat > /dev/null\n"
            "if test \"$1\" = pr; then\n"
            f"  printf '%s' '{PR_OUTPUT}'\n"
            "else\n"
            f"  printf '%s' '{MAIN_OUTPUT}'\n"
            "fi\n"
        )
        self.command_path.chmod(self.command_path.stat().st_mode | stat.S_IXUSR)
        self.environment = default_github_environment()
        self.environment["HOME"] = str(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def command(self) -> tuple[GitHubCommand, GitHubCommand]:
        return (
            GitHubCommand(
                argv=(
                    str(self.command_path),
                    "pr",
                    "list",
                    "--repo",
                    "simbiclaw/asdi",
                    "--state",
                    "open",
                ),
                environment=self.environment,
            ),
            GitHubCommand(
                argv=(
                    str(self.command_path),
                    "api",
                    "repos/simbiclaw/asdi/commits/main",
                ),
                environment=self.environment,
            ),
        )

    def reconciler(self) -> GitHubReconciler:
        pr_command, main_command = self.command()
        return GitHubReconciler(
            journal=self.journal,
            state_path=self.root / "github-state.json",
            repository="simbiclaw/asdi",
            base_ref="main",
            pr_command=pr_command,
            main_command=main_command,
        )

    def test_current_state_appends_normalized_events_once(self) -> None:
        first = self.reconciler().reconcile()
        self.assertEqual(first["appended_count"], 2)
        self.assertEqual(first["events"][0]["event_type"], "github.pull_request")
        self.assertEqual(
            first["events"][0]["payload"],
            {
                "pr_number": 7,
                "head_sha": HEAD,
                "base_ref": "main",
                "changed_paths": ["src/feature.py"],
            },
        )
        self.assertEqual(
            first["events"][1]["payload"],
            {"branch": "main", "commit": MAIN},
        )

        second = self.reconciler().reconcile()
        self.assertEqual(second["appended_count"], 0)
        self.assertEqual(second["duplicate_count"], 2)
        self.assertEqual(len(self.journal.load()), 2)

    def test_invalid_pull_request_is_rejected_without_event(self) -> None:
        pr_command, main_command = self.command()
        bad = self.root / "bad-gh"
        bad.write_text(
            "#!/bin/sh\n"
            "printf '%s' '[{\"number\":0,\"headRefOid\":\"short\",\"baseRefName\":\"other\",\"files\":[]}]'\n"
        )
        bad.chmod(bad.stat().st_mode | stat.S_IXUSR)
        reconciler = GitHubReconciler(
            journal=self.journal,
            state_path=self.root / "github-state.json",
            repository="simbiclaw/asdi",
            base_ref="main",
            pr_command=GitHubCommand(
                argv=(str(bad), "pr"), environment=self.environment
            ),
            main_command=main_command,
        )
        result = reconciler.reconcile()

        self.assertEqual(result["appended_count"], 1)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertIn(
            "number must be a positive integer",
            result["rejected"][0]["failures"],
        )
        self.assertEqual(
            [event["event_type"] for event in self.journal.load()],
            ["github.push"],
        )

    def test_command_failure_records_unhealthy_and_appends_nothing(self) -> None:
        failed = self.root / "failed-gh"
        failed.write_text("#!/bin/sh\nprintf 'gh: unavailable' >&2\nexit 17\n")
        failed.chmod(failed.stat().st_mode | stat.S_IXUSR)
        reconciler = GitHubReconciler(
            journal=self.journal,
            state_path=self.root / "health.json",
            repository="simbiclaw/asdi",
            base_ref="main",
            pr_command=GitHubCommand(
                argv=(str(failed), "pr"), environment=self.environment
            ),
            main_command=GitHubCommand(
                argv=(str(failed), "api"), environment=self.environment
            ),
        )
        with self.assertRaises(RuntimeError):
            reconciler.reconcile()

        health = json.loads((self.root / "health.json").read_text())
        self.assertFalse(health["healthy"])
        self.assertEqual(health["alert"], "github_reconciliation_failed")
        self.assertEqual(len(self.journal.load()), 0)

    def test_default_environment_does_not_inherit_credential_variables(self) -> None:
        os.environ["ASDI_TEST_TOKEN"] = "not-a-real-token"
        try:
            environment = default_github_environment(
                proxy_url="http://127.0.0.1:7890"
            )
        finally:
            os.environ.pop("ASDI_TEST_TOKEN", None)
        self.assertNotIn("ASDI_TEST_TOKEN", environment)
        self.assertNotIn("GH_TOKEN", environment)
        self.assertEqual(environment["HTTPS_PROXY"], "http://127.0.0.1:7890")
