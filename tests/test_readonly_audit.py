from __future__ import annotations

import json
import tempfile
import unittest
import subprocess
from unittest.mock import patch
from pathlib import Path

from tools.readonly_audit import export_commit, main

from tools.readonly_audit import build_command


ROOT = Path(__file__).resolve().parents[1]


class ReadOnlyAuditTests(unittest.TestCase):
    def test_exact_commit_export_is_safe_and_commit_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            destination = root / "export"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            (repo / "candidate.txt").write_text("exact candidate\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@invalid",
                    "commit",
                    "-m",
                    "candidate",
                ],
                check=True,
                capture_output=True,
            )
            commit = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            exported_commit = export_commit(repo, "HEAD", destination)
            self.assertEqual(exported_commit, commit)
            self.assertEqual(
                (destination / "candidate.txt").read_text(),
                "exact candidate\n",
            )
            self.assertFalse((destination / ".git").exists())
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
                audit_commit="a" * 40,
            )
            self.assertEqual(command[0], "fake-docker")
            self.assertEqual(command[command.index("--entrypoint") + 1], "/usr/bin/python3")
            self.assertEqual(command[-1], "/opt/asdi/skill/SKILL.md")
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
            self.assertIn(f"ASDI_AUDIT_COMMIT={'a' * 40}", command)

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

    def test_timeout_is_recorded_and_is_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("candidate", "specs", "skill", "reports"):
                (root / name).mkdir()
            report_dir = root / "reports"
            arguments = [
                "--candidate",
                str(root / "candidate"),
                "--specs",
                str(ROOT / "reference"),
                "--skill-root",
                str(ROOT / "skills/asdi-build-conformance"),
                "--report-dir",
                str(report_dir),
                "--timeout-seconds",
                "0.01",
                "--",
                "/bin/true",
            ]
            with patch(
                "tools.readonly_audit.subprocess.run",
                side_effect=TimeoutError("audit timeout"),
            ):
                exit_code = main(arguments)
            self.assertEqual(exit_code, 3)
            execution = (report_dir / "execution.json").read_text()
            self.assertIn('"timed_out": true', execution)

    def test_exact_commit_mode_exports_head_for_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            (repo / "candidate.txt").write_text("auditable\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@invalid",
                    "commit",
                    "-m",
                    "candidate",
                ],
                check=True,
                capture_output=True,
            )
            commit = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            report_dir = root / "reports"
            arguments = [
                "--git-repo",
                str(repo),
                "--commit",
                "HEAD",
                "--specs",
                str(ROOT / "reference"),
                "--skill-root",
                str(ROOT / "skills/asdi-build-conformance"),
                "--report-dir",
                str(report_dir),
                "--docker",
                "/usr/bin/true",
                "--",
                "/bin/true",
            ]
            exit_code = main(arguments)
            self.assertEqual(exit_code, 3)
            invocation = (report_dir / "invocation.json").read_text()
            self.assertIn(commit, invocation)
            self.assertIn("asdi-readonly-audit-candidate.", invocation)
            execution = json.loads((report_dir / "execution.json").read_text())
            self.assertFalse(execution["timed_out"])
            self.assertFalse(execution["report_validation"]["valid"])
            wrapper = (report_dir / "wrapper-report.json").read_text()
            self.assertIn('"accepted": false', wrapper)

    def test_exact_commit_mode_rejects_nonindependent_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            destination = root / "export"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            (repo / "candidate.txt").write_text("candidate\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@invalid",
                    "commit",
                    "-m",
                    "candidate",
                ],
                check=True,
                capture_output=True,
            )
            commit = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            destination.mkdir()
            report_path = destination / "conformance-report.json"
            report_dir = root / "reports"
            report_dir.mkdir()
            report = {
                "schema_version": "asdi.build-conformance-report/v1",
                "audit_date": "2026-11-19",
                "repo": "test",
                "branch": "main",
                "base_commit": "b" * 40,
                "candidate_commit": commit,
                "build_phase": "Pass 1 / Phase 1",
                "scope": "test",
                "spec_set": "REV K",
                "source_complete": True,
                "overall_result": "PASS",
                "executive_result": "test",
                "conformance_matrix": [],
                "findings": [],
                "tests_executed": [],
                "adversarial_checks": [],
                "phase_exit_decision": "test",
                "next_actions": [],
                "independent": False,
            }
            (report_dir / "conformance-report.json").write_text(json.dumps(report))
            exit_code = main(
                [
                    "--candidate",
                    str(destination),
                    "--commit",
                    commit,
                    "--specs",
                    str(ROOT / "reference"),
                    "--skill-root",
                    str(ROOT / "skills/asdi-build-conformance"),
                    "--report-dir",
                    str(root / "reports"),
                    "--docker",
                    "/usr/bin/true",
                    "--",
                    "/bin/true",
                ]
            )
            self.assertEqual(exit_code, 3)
            execution = json.loads((root / "reports/execution.json").read_text())
            validation = execution["report_validation"]
            self.assertEqual(validation["path"], str(report_dir / "conformance-report.json"))
            self.assertTrue(validation["exists"])
            self.assertFalse(validation["valid"])
            self.assertEqual(validation["failures"], ["independent must be true"])
            wrapper = json.loads((root / "reports/wrapper-report.json").read_text())
            self.assertFalse(wrapper["accepted"])

    def test_exact_commit_mode_accepts_independent_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "candidate"
            destination.mkdir()
            commit = "a" * 40
            report_dir = root / "reports"
            report_dir.mkdir()
            report_path = root / "reports" / "conformance-report.json"
            report = {
                "schema_version": "asdi.build-conformance-report/v1",
                "audit_date": "2026-11-19",
                "repo": "test",
                "branch": "main",
                "base_commit": "b" * 40,
                "candidate_commit": commit,
                "build_phase": "Pass 1 / Phase 1",
                "scope": "test",
                "spec_set": "REV K",
                "source_complete": True,
                "overall_result": "PASS",
                "executive_result": "test",
                "conformance_matrix": [],
                "findings": [],
                "tests_executed": [],
                "adversarial_checks": [],
                "phase_exit_decision": "test",
                "next_actions": [],
                "independent": True,
            }
            report_path.write_text(json.dumps(report))
            exit_code = main(
                [
                    "--candidate",
                    str(destination),
                    "--commit",
                    commit,
                    "--specs",
                    str(ROOT / "reference"),
                    "--skill-root",
                    str(ROOT / "skills/asdi-build-conformance"),
                    "--report-dir",
                    str(root / "reports"),
                    "--docker",
                    "/usr/bin/true",
                    "--",
                    "/bin/true",
                ]
            )
            self.assertEqual(exit_code, 0)
            execution = json.loads((root / "reports/execution.json").read_text())
            self.assertTrue(execution["report_validation"]["valid"])
            wrapper = json.loads((root / "reports/wrapper-report.json").read_text())
            self.assertTrue(wrapper["accepted"])
