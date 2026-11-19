from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from events.review import ReviewCommand, run_review


HEAD = "a" * 40
PACKET = {"head_sha": HEAD, "changed_paths": ["src/feature.py"]}


class ReviewPassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.reviewer = self.root / "reviewer.py"
        self.reviewer.write_text(
            "#!/usr/bin/env python3\n"
            "import argparse\n"
            "import json\n"
            "from pathlib import Path\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--packet', required=True)\n"
            "parser.add_argument('--diff', required=True)\n"
            "parser.add_argument('--output', required=True)\n"
            "arguments = parser.parse_args()\n"
            "packet = json.loads(Path(arguments.packet).read_text())\n"
            "Path(arguments.output).write_text(json.dumps({\n"
            "  'schema_version': 'asdi.review-result/v1',\n"
            "  'pass': 'review',\n"
            "  'model': 'local-review-model',\n"
            "  'independent_family': False,\n"
            "  'reviewed_commit': packet['head_sha'],\n"
            "  'status': 'pass',\n"
            "  'findings': [],\n"
            "}))\n"
        )
        self.reviewer.chmod(self.reviewer.stat().st_mode | stat.S_IXUSR)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def command(self) -> ReviewCommand:
        return ReviewCommand(
            name="local_review",
            argv=(
                "/usr/bin/python3",
                str(self.reviewer),
                "--packet",
                "{packet}",
                "--diff",
                "{diff}",
                "--output",
                "{output}",
            ),
            timeout_seconds=5,
            independent_family=False,
        )

    def test_explicit_reviewer_runs_read_only_and_passes_head_binding(self) -> None:
        result = run_review(packet=PACKET, diff="changed\n", command=self.command())
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["reviewed_commit"], HEAD)
        self.assertFalse(result["independent_family"])
        self.assertFalse(result["execution"]["timed_out"])
        self.assertEqual(result["execution"]["validation_failures"], [])

    def test_stale_review_output_is_invalid_and_blocked(self) -> None:
        self.reviewer.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "from pathlib import Path\n"
            "path = Path(r'{output}')\n"
            "path.write_text(json.dumps({'schema_version': 'asdi.review-result/v1', 'pass': 'review', 'model': 'x', 'independent_family': False, 'reviewed_commit': 'stale', 'status': 'pass', 'findings': []}))\n"
        )
        result = run_review(packet=PACKET, diff="changed\n", command=self.command())
        self.assertEqual(result["status"], "blocked")
        self.assertIn("reviewed_commit does not match PR head", result["execution"]["validation_failures"])

    def test_rejects_credential_like_reviewer_command(self) -> None:
        with self.assertRaisesRegex(ValueError, "credential-like"):
            ReviewCommand(
                name="unsafe",
                argv=("/usr/bin/env", "GITHUB_TOKEN=secret"),
            )
