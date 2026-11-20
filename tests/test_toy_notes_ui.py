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
    seed_note,
)


class ToyNotesUIFlagTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.servers: list = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.close()

    def start(self, db_path: Path, *, ui: bool, defect: bool = False):
        server = launch_product(db_path, self.directory / "run", ui=ui, defect=defect)
        self.servers.append(server)
        return server

    def test_ui_flag_defaults_off_and_changes_only_ui_route(self) -> None:
        off_db = self.directory / "off.sqlite3"
        on_db = self.directory / "on.sqlite3"
        seed_note(off_db)
        seed_note(on_db)
        off = self.start(off_db, ui=False)
        on = self.start(on_db, ui=True)

        disabled = off.request("/notes/ui")
        self.assertEqual(disabled["status"], 404)
        self.assertIn("ui_disabled", disabled["body"])

        enabled = on.request("/notes/ui")
        self.assertEqual(enabled["status"], 200)
        self.assertIn("<form", enabled["body"])
        self.assertIn("seed", enabled["body"])

        self.assertEqual(off.request("/healthz")["body"], on.request("/healthz")["body"])
        self.assertEqual(off.request("/notes")["body"], on.request("/notes")["body"])
        self.assertEqual(off.request("/readyz")["body"], on.request("/readyz")["body"])

        health = json.loads(on.request("/healthz")["body"])
        self.assertNotIn("notes_ui_enabled", health)

    def test_ui_form_creates_a_note_in_sqlite(self) -> None:
        db_path = self.directory / "ui.sqlite3"
        server = self.start(db_path, ui=True)
        submitted = server.request(
            "/notes",
            method="POST",
            payload={"title": "ui-proof", "body": "synthetic"},
            form=True,
        )
        self.assertEqual(submitted["status"], 201, submitted["body"])
        self.assertEqual(row_count(db_path), 1)
        self.assertIn("ui-proof", server.request("/notes/ui")["body"])

    def test_defect_injection_blocks_ui_form_without_a_new_row(self) -> None:
        db_path = self.directory / "ui-control.sqlite3"
        seed_note(db_path)
        server = self.start(db_path, ui=True, defect=True)
        submitted = server.request(
            "/notes",
            method="POST",
            payload={"title": "control", "body": "synthetic"},
            form=True,
        )
        self.assertEqual(submitted["status"], 500, submitted["body"])
        self.assertEqual(row_count(db_path), 1)
        self.assertNotIn("control", server.request("/notes/ui")["body"])

    def test_cli_and_ui_share_the_same_sqlite_file(self) -> None:
        db_path = self.directory / "shared.sqlite3"
        created = run_cli(PRODUCT_ROOT, db_path, "create", "--title", "from-cli")
        self.assertEqual(created.returncode, 0, created.stderr)
        server = self.start(db_path, ui=True)
        self.assertIn("from-cli", server.request("/notes/ui")["body"])


if __name__ == "__main__":
    unittest.main()
