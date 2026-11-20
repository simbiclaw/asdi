from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_toy_notes_support import (
    PRODUCT_ROOT,
    launch_product,
    row_count,
    run_cli,
)


class ToyNotesCLITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.db_path = self.directory / "notes.sqlite3"

    def test_create_list_read_and_export_json(self) -> None:
        created = run_cli(PRODUCT_ROOT, self.db_path, "create", "--title", "cli-proof", "--body", "synthetic")
        self.assertEqual(created.returncode, 0, created.stderr)
        note = json.loads(created.stdout)
        self.assertEqual(note["title"], "cli-proof")
        self.assertEqual(note["body"], "synthetic")
        self.assertEqual(row_count(self.db_path), 1)

        listed = run_cli(PRODUCT_ROOT, self.db_path, "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual([item["title"] for item in json.loads(listed.stdout)], ["cli-proof"])

        read = run_cli(PRODUCT_ROOT, self.db_path, "read", "--id", "1")
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(json.loads(read.stdout)["id"], 1)

        export_path = self.directory / "export.json"
        exported = run_cli(PRODUCT_ROOT, self.db_path, "export", "--out", str(export_path))
        self.assertEqual(exported.returncode, 0, exported.stderr)
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        self.assertEqual(payload, json.loads(listed.stdout))

    def test_defect_injection_blocks_cli_create(self) -> None:
        blocked = run_cli(PRODUCT_ROOT, self.db_path, "create", "--title", "control", defect=True)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("defect injection", blocked.stderr)
        self.assertEqual(row_count(self.db_path), 0)

        restored = run_cli(PRODUCT_ROOT, self.db_path, "create", "--title", "restored")
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(row_count(self.db_path), 1)


class ToyNotesHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.db_path = self.directory / "http.sqlite3"
        self.servers: list = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.close()

    def start(self, *, defect: bool = False):
        server = launch_product(
            self.db_path,
            self.directory / "run",
            defect=defect,
        )
        self.servers.append(server)
        return server

    def test_health_readiness_metrics_notes_and_post(self) -> None:
        server = self.start()
        health = server.request("/healthz")
        self.assertEqual(health["status"], 200)
        self.assertEqual(json.loads(health["body"])["status"], "ok")

        ready = server.request("/readyz")
        self.assertEqual(ready["status"], 200)
        self.assertEqual(json.loads(ready["body"])["db"], "ok")

        notes_before = server.request("/notes")
        self.assertEqual(notes_before["status"], 200)
        self.assertEqual(json.loads(notes_before["body"])["notes"], [])

        created = server.request(
            "/notes",
            method="POST",
            payload={"title": "http-proof", "body": "synthetic"},
        )
        self.assertEqual(created["status"], 201, created["body"])
        self.assertEqual(json.loads(created["body"])["title"], "http-proof")
        self.assertEqual(row_count(self.db_path), 1)

        notes_after = server.request("/notes")
        self.assertEqual([note["title"] for note in json.loads(notes_after["body"])["notes"]], ["http-proof"])

        metrics = server.request("/metrics")
        self.assertEqual(metrics["status"], 200)
        self.assertIn("toy_notes_requests_total", metrics["body"])
        self.assertIn("toy_notes_notes_total 1", metrics["body"])

    def test_defect_injection_is_reversible_across_processes(self) -> None:
        injected = self.start(defect=True)
        blocked = injected.request(
            "/notes",
            method="POST",
            payload={"title": "control", "body": "synthetic"},
        )
        self.assertEqual(blocked["status"], 500, blocked["body"])
        self.assertIn("defect injection", blocked["body"])
        self.assertEqual(row_count(self.db_path), 0)
        injected.close()

        restored = self.start()
        allowed = restored.request(
            "/notes",
            method="POST",
            payload={"title": "restored", "body": "synthetic"},
        )
        self.assertEqual(allowed["status"], 201, allowed["body"])
        self.assertEqual(row_count(self.db_path), 1)


if __name__ == "__main__":
    unittest.main()
