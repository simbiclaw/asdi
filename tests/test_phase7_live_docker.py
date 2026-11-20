"""Live-Docker Dockerfile check; skips cleanly without a local Docker daemon."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "pilots" / "toy_notes" / "Dockerfile"
CONTEXT = REPO_ROOT / "pilots" / "toy_notes"
BASE_IMAGE = "python:3.12-slim"
LIVE_TAG = "asdi-phase7-live-test:local"


class Phase7LiveDockerTests(unittest.TestCase):
    def test_dockerfile_builds_without_external_network(self) -> None:
        if shutil.which("docker") is None:
            self.skipTest("Docker CLI is not installed")
        version = subprocess.run(
            ["docker", "version"], capture_output=True, text=True, check=False, timeout=30
        )
        if version.returncode != 0:
            self.skipTest("Docker daemon is unavailable")
        base = subprocess.run(
            ["docker", "image", "inspect", BASE_IMAGE],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if base.returncode != 0:
            self.skipTest(f"{BASE_IMAGE} is not cached; external pulls are not allowed")
        self.assertTrue(DOCKERFILE.is_file())
        with tempfile.TemporaryDirectory(prefix="asdi-phase7-live-docker-") as temporary:
            iidfile = Path(temporary) / "iid"
            result = subprocess.run(
                [
                    "docker",
                    "build",
                    "--network=none",
                    "--file",
                    str(DOCKERFILE),
                    "--tag",
                    LIVE_TAG,
                    "--iidfile",
                    str(iidfile),
                    str(CONTEXT),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(iidfile.is_file())
            self.assertIn("sha256:", iidfile.read_text(encoding="utf-8"))
        self.addCleanup(
            subprocess.run,
            ["docker", "image", "rm", "--force", LIVE_TAG],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
