from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.readonly_audit import build_command


ROOT = Path(__file__).resolve().parents[1]


class ReadOnlyAuditTests(unittest.TestCase):
    def test_auditor_has_no_network_write_docker_socket_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("candidate", "specs", "skill", "reports"):
                (root / name).mkdir()
            command = build_command(
                docker="fake-docker",
                image="auditor",
                candidate=root / "candidate",
                specs=ROOT / "reference",
                report_dir=root / "reports",
                skill_root=ROOT / "skills/asdi-build-conformance",
                auditor_command=["/usr/bin/python3", "/opt/asdi/skill/SKILL.md"],
            )
            self.assertEqual(command[0], "fake-docker")
            self.assertIn("--network", command)
            self.assertIn("none", command)
            self.assertIn("--cap-drop", command)
            self.assertIn("ALL", command)
            self.assertIn("--read-only", command)
            self.assertIn("--user", command)
            self.assertIn("1001:1001", command)
            self.assertFalse(any("/var/run/docker.sock" in item for item in command))
            self.assertTrue(
                any("destination=/workspace,readonly" in item for item in command)
            )
            self.assertFalse(
                any("GITHUB_TOKEN" in item for item in command),
            )

    def test_rejects_docker_socket_and_credential_injection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("candidate", "specs", "skill", "reports"):
                (root / name).mkdir()
            common = {
                "docker": "docker",
                "image": "auditor",
                "candidate": root / "candidate",
                "specs": ROOT / "reference",
                "report_dir": root / "reports",
                "skill_root": ROOT / "skills/asdi-build-conformance",
            }
            with self.assertRaisesRegex(ValueError, "Docker"):
                build_command(**common, auditor_command=["docker", "ps"])
            with self.assertRaisesRegex(ValueError, "token"):
                build_command(**common, auditor_command=["env", "GITHUB_TOKEN=x"])

    def test_rejects_missing_mount_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "candidate").mkdir()
            (root / "specs").mkdir()
            (root / "reports").mkdir()
            with self.assertRaisesRegex(ValueError, "skill_root"):
                build_command(
                    docker="docker",
                    image="auditor",
                    candidate=root / "candidate",
                    specs=root / "specs",
                    report_dir=root / "reports",
                    skill_root=root / "missing",
                    auditor_command=["true"],
                )
