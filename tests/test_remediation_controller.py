from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from launcher.remediation import (
    RemediationConfig,
    RemediationController,
)
from launcher.remediation_cli import main as remediation_cli_main


class RemediationControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.state_root = self.root / "remediation"
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(self.repo)], check=True, capture_output=True)
        (self.repo / "implementation.txt").write_text("initial\n")
        (self.repo / "AGENTS.md").write_text("ASDI implementation rules\n")
        self._git(["add", "."])
        self._git([
            "-c", "user.name=Test",
            "-c", "user.email=test@invalid",
            "commit", "-m", "initial",
        ])

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _git(self, arguments: list[str]) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            check=True,
            capture_output=True,
        )

    def _script(self, name: str, body: str) -> Path:
        path = self.scripts / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    def _builder(self) -> Path:
        return self._script(
            "builder.sh",
            """#!/bin/sh
set -eu
cycle=${ASDI_REMEDIATION_CYCLE:-$1}
printf 'fixed-cycle-%s\\n' "$cycle" > implementation.txt
git add implementation.txt
git -c user.name=Builder -c user.email=builder@invalid commit -m "remediation $cycle"
""",
        )

    def _verifier(self, mode: str) -> Path:
        valid_modes = {"auto", "pass", "fail", "defect"}
        if mode not in valid_modes:
            raise ValueError(mode)
        body = f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

MODE = {mode!r}
report_path = Path(sys.argv[1])
implementation = Path("implementation.txt")
fixed = implementation.exists() and implementation.read_text().startswith("fixed-cycle-")

if MODE == "pass":
    result = "pass"
    spec_feedback = {{"required": False}}
elif MODE == "fail":
    result = "fail"
    spec_feedback = {{"required": False}}
elif MODE == "defect":
    result = "fail"
    spec_feedback = {{
        "required": True,
        "defect": "requirement is technically infeasible",
    }}
else:
    result = "pass" if fixed else "fail"
    spec_feedback = {{"required": False}}

report = {{
    "schema_version": "asdi.conformance-report/v1",
    "result": result,
    "independent": True,
    "findings": [],
    "blocked_reason": None,
    "spec_feedback": spec_feedback,
}}
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, indent=2) + "\\n")
raise SystemExit(0 if result == "pass" else 1)
"""
        return self._script(f"verifier-{mode}.sh", body)

    def _controller(
        self,
        verifier: Path,
        builder_override: Path | None = None,
        *,
        state_name: str | None = None,
    ) -> RemediationController:
        return RemediationController(
            self.state_root / (state_name or self._testMethodName),
            RemediationConfig(
                requirement_id="R-REV-K-LAUNCHER",
                repo_root=self.repo,
                base_revision="main",
                phase="Pass 1 / Phase 1",
                scope="launcher verifier authority",
                builder_command=(str(builder_override or self._builder()),),
                verifier_command=(str(verifier), "{report}"),
                spec_paths=("AGENTS.md",),
            ),
        )

    def test_initial_pass_does_not_count_a_remediation_cycle(self) -> None:
        controller = self._controller(self._verifier("pass"))
        result = controller.audit()
        self.assertEqual(result["action"], "accepted_on_initial_audit")
        self.assertEqual(controller.state["attempted_remediation_cycles"], 0)

    def test_one_fresh_builder_cycle_and_fresh_verifier_can_accept(self) -> None:
        controller = self._controller(self._verifier("auto"))
        result = controller.audit()
        self.assertEqual(result["action"], "accepted_after_remediation")
        self.assertEqual(result["cycle"], 1)
        self.assertEqual(controller.state["attempted_remediation_cycles"], 1)
        cycle = controller.state["cycles"][0]
        self.assertTrue(cycle["fresh_candidate"])
        self.assertNotEqual(cycle["candidate_revision"], cycle["before_revision"])

    def test_two_failures_escalate_and_hold_affected_work(self) -> None:
        controller = self._controller(self._verifier("fail"))
        result = controller.audit()
        self.assertEqual(result["action"], "escalated_to_specification_feedback")
        self.assertEqual(result["trigger"], "persistent_failure")
        self.assertEqual(controller.state["attempted_remediation_cycles"], 2)
        self.assertTrue(controller.state["hold"]["active"])
        with self.assertRaisesRegex(RuntimeError, "specification feedback hold"):
            controller.enforce_hold()
        self.assertTrue((controller.root / "spec-feedback-report.md").is_file())

    def test_spec_defect_escalates_immediately_without_cycles(self) -> None:
        controller = self._controller(self._verifier("defect"))
        result = controller.audit()
        self.assertEqual(result["action"], "escalated_to_specification_feedback")
        self.assertEqual(result["trigger"], "specification_defect")
        self.assertEqual(controller.state["attempted_remediation_cycles"], 0)
        self.assertTrue(controller.state["hold"]["active"])

    def test_builder_spec_mutation_escalates_immediately(self) -> None:
        builder = self._script(
            "mutating-builder.sh",
            """#!/bin/sh
set -eu
printf 'agent must not edit specs\\n' >> AGENTS.md
git add AGENTS.md
git -c user.name=Builder -c user.email=builder@invalid commit -m 'spec mutation'
""",
        )
        controller = self._controller(self._verifier("fail"), builder_override=builder)
        result = controller.audit()
        self.assertEqual(result["action"], "escalated_to_specification_feedback")
        self.assertEqual(
            result["trigger"],
            "specification_mutation_during_builder_remediation",
        )

    def test_owner_decision_is_recorded_and_releases_hold(self) -> None:
        controller = self._controller(self._verifier("fail"))
        controller.audit()
        feedback = controller.record_owner_decision(
            owner="repository_owner",
            decision="confirm_original_requirement",
            direction="Continue implementation; do not weaken verification.",
        )
        self.assertEqual(feedback["status"], "owner_decision_recorded")
        self.assertFalse(controller.state["hold"]["active"])
        self.assertEqual(
            controller.state["status"],
            "owner_confirm_original_requirement",
        )

    def test_cli_can_audit_and_report_durable_state(self) -> None:
        state_root = self.state_root / "cli"
        builder = self._builder()
        verifier = self._verifier("pass")
        arguments = [
            "--state-root", str(state_root),
            "audit",
            "--requirement-id", "R-REV-K-LAUNCHER",
            "--repo-root", str(self.repo),
            "--base-revision", "main",
            "--phase", "Pass 1 / Phase 1",
            "--scope", "launcher verifier authority",
            "--builder-command", str(builder),
            "--verifier-command", f"{verifier} {{report}}",
            "--spec-path", "AGENTS.md",
        ]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = remediation_cli_main(arguments)
        self.assertEqual(exit_code, 0)
        self.assertIn("accepted_on_initial_audit", output.getvalue())

        status_arguments = ["--state-root", str(state_root), "status"]
        status_output = io.StringIO()
        with contextlib.redirect_stdout(status_output):
            exit_code = remediation_cli_main(status_arguments)
        self.assertEqual(exit_code, 0)
        self.assertIn('"status": "verified"', status_output.getvalue())
        self.assertTrue((state_root / "state.json").is_file())
