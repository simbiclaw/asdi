"""Local SQLite dump, restore integrity and restore drill tests."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from backup.local import BackupError, dump_database, integrity_check, restore_database, run_restore_drill
from tests.test_phase7_support import read_json


class Phase7BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="asdi-phase7-backup-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "toy-notes.sqlite3"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
            connection.executemany(
                "INSERT INTO notes (title) VALUES (?)",
                [("alpha",), ("beta",), ("gamma",)],
            )

    def test_dump_and_restore_preserve_rows_and_integrity(self) -> None:
        dump = self.root / "snapshot.sqlite3"
        target = self.root / "restored.sqlite3"
        dump_record = dump_database(self.database, dump)
        self.assertEqual(dump_record["integrity_check"], "ok")
        restore_record = restore_database(dump, target)
        self.assertEqual(restore_record["dump_integrity_check"], "ok")
        self.assertEqual(restore_record["restored_integrity_check"], "ok")
        with sqlite3.connect(target) as connection:
            titles = [row[0] for row in connection.execute("SELECT title FROM notes ORDER BY title")]
        self.assertEqual(titles, ["alpha", "beta", "gamma"])

    def test_restore_drill_writes_passing_record(self) -> None:
        record_path = self.root / "restore-drill.json"
        record = run_restore_drill(self.database, record_path)
        self.assertTrue(record["passed"])
        self.assertEqual(record["dump_integrity_check"], "ok")
        self.assertEqual(record["restored_integrity_check"], "ok")
        self.assertEqual(record["table_row_counts"]["notes"], {"source": 3, "restored": 3})
        self.assertTrue(read_json(record_path)["passed"])

    def test_corrupt_dump_fails_closed(self) -> None:
        corrupt = self.root / "corrupt.sqlite3"
        corrupt.write_bytes(b"this is not a sqlite database")
        with self.assertRaises(BackupError):
            integrity_check(corrupt)
        with self.assertRaises(BackupError):
            restore_database(corrupt, self.root / "bad-restore.sqlite3")


if __name__ == "__main__":
    unittest.main()
