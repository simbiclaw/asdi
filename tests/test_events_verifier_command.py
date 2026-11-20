#!/usr/bin/env python3

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from events.verifier_command import (
    VerificationCommand,
    run_verification,
    verification_execution_event_payload,
)


HEAD = "a" * 40


class VerificationCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.verifier = self.root / "verifier"
        self.verifier.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            "head, output = sys.argv[1], Path(sys.argv[2])\n"
            "report = {\n"
            "    'schema_version': 'asdi.verifier-only-result/v1',\n"
            "    'run_id': 'rv-command',\n"
            "    'status': 'succeeded',\n"
            "    'revision': head,\n"
            "    'commit': head,\n"
            "    'source': 'pr-head',\n"
            "    'checks': [{'id': 'static:test', 'status': 'pass'}],\n"
            "    'evidence': {\n"
            "        'valid': True,\n"
            "        'manifest_id': 'm-verifier',\n"
            "        'statement': {'subject': [{'digest': {'gitCommit': head}}],\n"
            "                      'predicate': {'source': 'pr-head'}},\n"
            "        'result': {'schema': 2, 'run_id': 'rv-command', 'commit': head,\n"
            "                   'features': [{'id': 'feature:test', 'status': 'pass',\n"
            "                                 'control': 'caught', 'evidence': [],\n"
            "                                 'limits': []}]},\n"
            "    },\n"
            "    'runtime': {'network': 'none', 'socket_mounted': False,\n"
            "                'secrets_mounted': False, 'agent_started': False},\n"
            "}\n"
            "output.write_text(json.dumps(report))\n"
        )
        self.verifier.chmod(self.verifier.stat().st_mode | stat.S_IXUSR)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def command(self) -> VerificationCommand:
        return VerificationCommand(
            name="local-verifier",
            argv=("/usr/bin/python3", str(self.verifier), "{head}", "{output}"),
            timeout_seconds=10,
        )

    def test_valid_command_maps_to_green_verifier_payload(self) -> None:
        result = run_verification(command=self.command(), head_sha=HEAD)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["execution"]["validation_failures"], [])

        payload = verification_execution_event_payload(
            packet={"pr_number": 7, "head_sha": HEAD},
            result=result,
            ci_status="pass",
        )
        self.assertEqual(payload["verifier"]["status"], "pass")
        self.assertEqual(payload["verifier"]["manifest_id"], "m-verifier")
        self.assertEqual(payload["statuses"], {"ci": "pass"})

    def test_missing_output_is_fail_closed(self) -> None:
        command = self.command()
        broken = self.root / "broken-verifier"
        broken.write_text("#!/usr/bin/env true\n")
        broken.chmod(broken.stat().st_mode | stat.S_IXUSR)
        command = VerificationCommand(
            name="broken-verifier",
            argv=(str(broken), "{head}", "{output}"),
            timeout_seconds=10,
        )
        result = run_verification(command=command, head_sha=HEAD)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["execution"]["validation_failures"])
        payload = verification_execution_event_payload(
            packet={"pr_number": 7, "head_sha": HEAD},
            result=result,
            ci_status="pass",
        )
        self.assertEqual(payload["verifier"]["status"], "fail")
        self.assertIn("verifier output is not an object", payload["verifier"]["failures"])

    def test_stale_or_invalid_result_is_fail_closed(self) -> None:
        command = self.command()
        broken = self.root / "stale-verifier"
        broken.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            "Path(sys.argv[2]).write_text('{\"not\":\"a verifier result\"}')\n"
        )
        broken.chmod(broken.stat().st_mode | stat.S_IXUSR)
        command = VerificationCommand(
            name="stale-verifier",
            argv=(str(broken), "{head}", "{output}"),
            timeout_seconds=10,
        )
        result = run_verification(command=command, head_sha=HEAD)
        self.assertEqual(result["status"], "failed")
        payload = verification_execution_event_payload(
            packet={"pr_number": 7, "head_sha": HEAD},
            result=result,
            ci_status="pass",
        )
        self.assertEqual(payload["verifier"]["status"], "fail")

    def test_failed_status_cannot_promote_valid_evidence(self) -> None:
        command = self.command()
        failed = self.root / "failed-verifier"
        failed.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            "head, output = sys.argv[1], Path(sys.argv[2])\n"
            "report = {\n"
            "    'schema_version': 'asdi.verifier-only-result/v1',\n"
            "    'run_id': 'rv-command',\n"
            "    'status': 'failed',\n"
            "    'revision': head,\n"
            "    'commit': head,\n"
            "    'source': 'pr-head',\n"
            "    'checks': [{'id': 'static:test', 'status': 'pass'}],\n"
            "    'evidence': {\n"
            "        'valid': True,\n"
            "        'manifest_id': 'm-verifier',\n"
            "        'statement': {\n"
            "            'subject': [{'digest': {'gitCommit': head}}],\n"
            "            'predicate': {'source': 'pr-head'},\n"
            "        },\n"
            "        'result': {\n"
            "            'schema': 2,\n"
            "            'run_id': 'rv-command',\n"
            "            'commit': head,\n"
            "            'features': [{\n"
            "                'id': 'feature:test',\n"
            "                'status': 'pass',\n"
            "                'control': 'caught',\n"
            "                'evidence': [],\n"
            "                'limits': [],\n"
            "            }],\n"
            "        },\n"
            "    },\n"
            "    'runtime': {\n"
            "        'network': 'none',\n"
            "        'socket_mounted': False,\n"
            "        'secrets_mounted': False,\n"
            "        'agent_started': False,\n"
            "    },\n"
            "}\n"
            "output.write_text(json.dumps(report))\n"
            "raise SystemExit(3)\n"
        )
        failed.chmod(failed.stat().st_mode | stat.S_IXUSR)
        command = VerificationCommand(
            name="failed-verifier",
            argv=("/usr/bin/python3", str(failed), "{head}", "{output}"),
            timeout_seconds=10,
        )
        result = run_verification(command=command, head_sha=HEAD)
        payload = verification_execution_event_payload(
            packet={"pr_number": 7, "head_sha": HEAD},
            result=result,
            ci_status="pass",
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(payload["verifier"]["status"], "fail")
        self.assertIn(
            "verifier execution status is not succeeded",
            payload["verifier"]["failures"],
        )

    def test_rejects_credentials_and_relative_commands(self) -> None:
        with self.assertRaises(ValueError):
            VerificationCommand(
                name="bad",
                argv=("/usr/bin/env", "ASDI_TOKEN=bad"),
            )
        with self.assertRaises(ValueError):
            VerificationCommand(name="relative", argv=("python3", "--version"))
