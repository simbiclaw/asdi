"""Flag default-off, expiry sweep and cleanup issue tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from exposure.cli import (
    ISSUE_SCHEMA,
    FlagError,
    kill_flag,
    keep_flag,
    set_flag,
    status,
    sweep_expired,
)
from tests.test_phase7_support import read_json


class Phase7ExposureTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="asdi-phase7-exposure-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.flags = self.root / "flags.json"
        self.issues = self.root / "issues"

    def test_flags_default_off(self) -> None:
        self.assertEqual(status(self.flags), {"schema_version": "asdi.flags/v1", "flags": {}})
        self.assertFalse(status(self.flags, "ramp")["enabled"])

    def test_decision_reference_is_required(self) -> None:
        with self.assertRaisesRegex(FlagError, "decision reference"):
            set_flag(self.flags, "ramp", decision="", expires_at="2027-01-01T00:00:00Z")

    def test_set_keep_and_kill(self) -> None:
        first = "2026-12-01T00:00:00Z"
        later = "2027-01-01T00:00:00Z"
        set_flag(self.flags, "ramp", decision="ADR-0003", expires_at=first)
        self.assertTrue(status(self.flags, "ramp")["enabled"])
        keep_flag(self.flags, "ramp", decision="ADR-0003", expires_at=later)
        self.assertEqual(read_json(self.flags)["flags"]["ramp"]["expires_at"], later)
        kill_flag(self.flags, "ramp", decision="ADR-0003")
        self.assertFalse(status(self.flags, "ramp")["enabled"])

    def test_expired_flag_is_killed_and_cleanup_issue_is_written(self) -> None:
        set_flag(
            self.flags,
            "expiry-check",
            decision="ADR-0003",
            expires_at="2026-11-19T00:00:00Z",
        )
        now = datetime(2026, 11, 20, tzinfo=timezone.utc)
        issues = sweep_expired(self.flags, self.issues, now=now)
        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue["schema_version"], ISSUE_SCHEMA)
        self.assertEqual(issue["flag"], "expiry-check")
        self.assertEqual(issue["classification"], "judgment")
        self.assertFalse(issue["merge_policy_changed"])
        self.assertEqual(read_json(issue["path"])["flag"], "expiry-check")
        self.assertFalse(status(self.flags, "expiry-check")["enabled"])
        self.assertTrue(read_json(self.flags)["flags"]["expiry-check"]["killed_by_sweep"])

    def test_unexpired_flag_is_kept(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        set_flag(self.flags, "future", decision="ADR-0003", expires_at=future)
        self.assertEqual(
            sweep_expired(self.flags, self.issues, now=datetime.now(timezone.utc)), []
        )
        self.assertTrue(status(self.flags, "future")["enabled"])


if __name__ == "__main__":
    unittest.main()
