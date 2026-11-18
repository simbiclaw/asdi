from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from launcher.static_gates import gate_passes, run_checks


class StaticGateTests(unittest.TestCase):
    def test_only_blocking_gates_authorize_green(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake_docker = Path(temporary) / "docker"
            fake_docker.write_text("#!/bin/sh\nexit 0\n")
            fake_docker.chmod(0o755)
            checks = run_checks(
                docker=str(fake_docker),
                image="verifier",
                manifest={
                    "checks": [
                        {
                            "id": "advisory",
                            "command": ["true"],
                            "blocking": False,
                            "timeout_seconds": 1,
                        },
                        {
                            "id": "required",
                            "command": ["true"],
                            "blocking": True,
                            "timeout_seconds": 1,
                        },
                    ]
                },
                run_id="r-fixture",
                commit="a" * 40,
                mounts=[],
                timeout_scale=1.0,
            )
            self.assertEqual([check["status"] for check in checks], ["pass", "pass"])
            self.assertTrue(gate_passes(checks))
            checks[1]["status"] = "fail"
            self.assertFalse(gate_passes(checks))

    def test_timeout_is_error_even_for_advisory_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fake_docker = Path(temporary) / "docker"
            fake_docker.write_text("#!/bin/sh\nsleep 2\n")
            fake_docker.chmod(0o755)
            checks = run_checks(
                docker=str(fake_docker),
                image="verifier",
                manifest={
                    "checks": [
                        {
                            "id": "slow",
                            "command": ["true"],
                            "blocking": False,
                            "timeout_seconds": 1,
                        },
                    ]
                },
                run_id="r-fixture",
                commit="a" * 40,
                mounts=[],
                timeout_scale=0.001,
            )
            self.assertEqual(checks[0]["status"], "error")
            self.assertTrue(gate_passes(checks))


if __name__ == "__main__":
    unittest.main()
