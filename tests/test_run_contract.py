from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from asdi.run_contract import (
    AUTHORED_FIELDS,
    DEFAULT_CONFIG,
    RunContractValidationError,
    build_run_contract,
    validate_run_contract,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "fixtures" / "run_contracts"


def issue_codes(error: RunContractValidationError) -> set[str]:
    return {issue.code for issue in error.issues}


class RunContractTests(unittest.TestCase):
    def test_builder_supplies_central_provisional_defaults(self) -> None:
        contract = build_run_contract(
            objective="Objective",
            why="Why",
            constraints=[],
            out_of_scope=[],
            done_check={
                "description": "Tests pass",
                "argv": ["python3", "-m", "unittest", "discover"],
            },
            human_provided=["objective", "why"],
            lead_agent_authored=["constraints", "out_of_scope", "done_check"],
        )
        validated = validate_run_contract(contract)
        self.assertEqual(validated["guardrails"]["max_turns"], 200)
        self.assertEqual(validated["guardrails"]["max_spend_usd"], 8)
        self.assertEqual(validated["guardrails"]["wall_clock_seconds"], 5400)
        self.assertEqual(validated["boundaries"]["max_changed_lines"], 400)
        self.assertFalse(validated["boundaries"]["production_access"])
        self.assertFalse(validated["boundaries"]["irreversible_actions"])
        self.assertEqual(
            set(validated["provenance"]["human_provided"])
            | set(validated["provenance"]["lead_agent_authored"]),
            set(AUTHORED_FIELDS),
        )

    def test_default_fixture_is_valid(self) -> None:
        with (FIXTURE_ROOT / "valid" / "default.json").open(
            "r", encoding="utf-8"
        ) as handle:
            contract = json.load(handle)
        validated = validate_run_contract(contract)
        self.assertEqual(
            validated["output"],
            {"kind": "pull_request", "branch": "asdi/010-run-contract"},
        )

    def test_empty_optional_lists_are_explicit_and_valid(self) -> None:
        with (FIXTURE_ROOT / "valid" / "empty_optional_lists.json").open(
            "r", encoding="utf-8"
        ) as handle:
            contract = json.load(handle)
        self.assertEqual(contract["constraints"], [])
        self.assertEqual(contract["out_of_scope"], [])
        self.assertEqual(validate_run_contract(contract)["constraints"], [])

    def test_validated_contract_is_a_defensive_copy(self) -> None:
        contract = {
            "schema_version": "asdi.run-contract/v1",
            "task_type": "feature",
            "objective": "Objective",
            "why": "Why",
            "constraints": [],
            "out_of_scope": [],
            "done_check": {
                "description": "Tests pass",
                "argv": ["pytest", "-q"],
            },
            "boundaries": {
                "protected_paths": ["CODEOWNERS"],
                "max_changed_lines": 400,
                "network": {"mode": "deny_all"},
                "production_access": False,
                "irreversible_actions": False,
            },
            "guardrails": {
                "max_turns": 200,
                "max_spend_usd": 8,
                "wall_clock_seconds": 5400,
            },
            "output": {"kind": "report"},
            "provenance": {
                "human_provided": ["objective", "why"],
                "lead_agent_authored": [
                    "constraints",
                    "out_of_scope",
                    "done_check",
                ],
                "platform_defaults": [
                    "boundaries",
                    "guardrails",
                    "output",
                    "task_type",
                ],
            },
        }
        original = copy.deepcopy(contract)
        validated = validate_run_contract(contract)
        validated["objective"] = "mutated"
        validated["constraints"].append("mutated")
        self.assertEqual(contract, original)

    def test_missing_required_fields_fail(self) -> None:
        cases = {
            "missing_objective.json": {"missing", "incomplete"},
            "missing_done_check.json": {"missing", "incomplete"},
        }
        for filename, expected_codes in cases.items():
            with self.subTest(fixture=filename):
                with (FIXTURE_ROOT / "invalid" / filename).open(
                    "r", encoding="utf-8"
                ) as handle:
                    contract = json.load(handle)
                with self.assertRaises(RunContractValidationError) as raised:
                    validate_run_contract(contract)
                self.assertTrue(expected_codes & issue_codes(raised.exception))

    def test_malformed_and_unsafe_commands_fail(self) -> None:
        cases = {
            "shell_command.json": {"type"},
            "unsafe_metacharacter.json": {"unsafe_command"},
            "disallowed_executable.json": {"disallowed_executable"},
        }
        for filename, expected_codes in cases.items():
            with self.subTest(fixture=filename):
                with (FIXTURE_ROOT / "invalid" / filename).open(
                    "r", encoding="utf-8"
                ) as handle:
                    contract = json.load(handle)
                with self.assertRaises(RunContractValidationError) as raised:
                    validate_run_contract(contract)
                self.assertTrue(expected_codes & issue_codes(raised.exception))

    def test_invalid_budgets_fail(self) -> None:
        cases = {
            "negative_budget.json": {"invalid_budget"},
            "zero_wall_clock.json": {"invalid_budget"},
        }
        for filename, expected_codes in cases.items():
            with self.subTest(fixture=filename):
                with (FIXTURE_ROOT / "invalid" / filename).open(
                    "r", encoding="utf-8"
                ) as handle:
                    contract = json.load(handle)
                with self.assertRaises(RunContractValidationError) as raised:
                    validate_run_contract(contract)
                self.assertTrue(expected_codes & issue_codes(raised.exception))

    def test_unsupported_output_and_forbidden_production_access_fail(self) -> None:
        cases = {
            "unsupported_output.json": {"unsupported"},
            "production_access.json": {"forbidden"},
        }
        for filename, expected_codes in cases.items():
            with self.subTest(fixture=filename):
                with (FIXTURE_ROOT / "invalid" / filename).open(
                    "r", encoding="utf-8"
                ) as handle:
                    contract = json.load(handle)
                with self.assertRaises(RunContractValidationError) as raised:
                    validate_run_contract(contract)
                self.assertTrue(expected_codes & issue_codes(raised.exception))

    def test_unapproved_default_increase_and_bad_provenance_fail(self) -> None:
        cases = {
            "unapproved_override.json": {"unapproved_override"},
            "bad_provenance.json": {"conflict"},
            "unknown_provenance_field.json": {"unknown_field"},
        }
        for filename, expected_codes in cases.items():
            with self.subTest(fixture=filename):
                with (FIXTURE_ROOT / "invalid" / filename).open(
                    "r", encoding="utf-8"
                ) as handle:
                    contract = json.load(handle)
                with self.assertRaises(RunContractValidationError) as raised:
                    validate_run_contract(contract)
                self.assertTrue(expected_codes & issue_codes(raised.exception))

    def test_allowed_override_reason_can_raise_within_ceiling(self) -> None:
        with (FIXTURE_ROOT / "valid" / "default.json").open(
            "r", encoding="utf-8"
        ) as handle:
            contract = json.load(handle)
        contract["guardrails"]["max_turns"] = 250
        contract["guardrails"]["override_reason"] = "owner_approved"
        validated = validate_run_contract(contract)
        self.assertEqual(validated["guardrails"]["max_turns"], 250)

    def test_all_fixture_files_pass_through_cli_appropriately(self) -> None:
        for group, expected_status in (("valid", 0), ("invalid", 2)):
            for fixture in sorted((FIXTURE_ROOT / group).glob("*.json")):
                with self.subTest(fixture=fixture.name):
                    env = os.environ.copy()
                    env["PYTHONPATH"] = str(REPO_ROOT / "src")
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "asdi.run_contract",
                            "validate",
                            str(fixture),
                        ],
                        env=env,
                        cwd=REPO_ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(completed.returncode, expected_status)


if __name__ == "__main__":
    unittest.main()
