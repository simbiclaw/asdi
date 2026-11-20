from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from launcher.static_gates import gate_passes, run_checks


class StaticGateTests(unittest.TestCase):
    def run_one(self, returncode: int, *, blocking: bool) -> list[dict]:
        completed = subprocess.CompletedProcess([], returncode, "out", "err")
        with patch("launcher.static_gates.subprocess.run", return_value=completed):
            checks = run_checks(
                docker="docker",
                image="verifier",
                manifest={
                    "checks": [
                        {
                            "id": "advisory",
                            "command": ["/bin/true"],
                            "blocking": blocking,
                            "timeout_seconds": 1,
                        }
                    ]
                },
                run_id="r-test",
                commit="c" * 40,
                mounts=[],
            )
        checks.append({"id": "static:required", "status": "pass", "blocking": True})
        return checks

    def test_successful_advisory_check_passes(self) -> None:
        checks = self.run_one(0, blocking=False)
        self.assertEqual(checks[0]["status"], "pass")
        self.assertFalse(checks[0]["blocking"])
        self.assertTrue(gate_passes(checks))

    def test_failed_advisory_check_does_not_authorize_or_block_green(self) -> None:
        checks = self.run_one(1, blocking=False)
        self.assertEqual(checks[0]["status"], "fail")
        self.assertFalse(checks[0]["blocking"])
        self.assertTrue(gate_passes(checks))

    def test_timeout_is_error_even_for_advisory_check(self) -> None:
        with patch(
            "launcher.static_gates.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=[], timeout=1),
        ):
            checks = run_checks(
                docker="docker",
                image="verifier",
                manifest={
                    "checks": [
                        {
                            "id": "advisory",
                            "command": ["/bin/true"],
                            "blocking": False,
                            "timeout_seconds": 1,
                        }
                    ]
                },
                run_id="r-test",
                commit="c" * 40,
                mounts=[],
            )
        self.assertEqual(checks[0]["status"], "error")
        checks.append({"id": "static:required", "status": "pass", "blocking": True})
        self.assertFalse(gate_passes(checks))

    def test_timeout_kills_and_removes_named_container(self) -> None:
        timeout = subprocess.TimeoutExpired(cmd=[], timeout=1)
        cleanup = subprocess.CompletedProcess([], 0, "", "")
        with patch(
            "launcher.static_gates.subprocess.run",
            side_effect=[timeout, cleanup, cleanup],
        ) as runner:
            checks = run_checks(
                docker="docker",
                image="verifier",
                manifest={
                    "checks": [
                        {
                            "id": "hanging check",
                            "command": ["/bin/sleep"],
                            "blocking": True,
                            "timeout_seconds": 1,
                        }
                    ]
                },
                run_id="r-test",
                commit="c" * 40,
                mounts=[],
            )

        check = checks[0]
        self.assertEqual(check["status"], "error")
        self.assertTrue(check["timeout_killed"])
        self.assertEqual(len(check["timeout_cleanup"]), 2)
        self.assertEqual(
            runner.call_args_list[0].args[0][runner.call_args_list[0].args[0].index("--name") + 1],
            "asdi-static-r-test-hanging-check",
        )
        self.assertEqual(
            runner.call_args_list[1].args[0],
            ["docker", "kill", "asdi-static-r-test-hanging-check"],
        )
        self.assertEqual(
            runner.call_args_list[2].args[0],
            ["docker", "rm", "-f", "asdi-static-r-test-hanging-check"],
        )
