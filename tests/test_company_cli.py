from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.company_cli import main


class CompanyCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.output = io.StringIO()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def cli(self, *arguments: str) -> dict | list:
        self.output = io.StringIO()
        result = main(list(arguments), stdout=self.output)
        self.assertEqual(result, 0, self.output.getvalue())
        return json.loads(self.output.getvalue())

    def test_admit_show_list_events_and_product_summary(self) -> None:
        mission = self.cli(
            "--root",
            str(self.root),
            "admit",
            "--objective",
            "Implement a durable operational surface",
            "--why",
            "ASDI must remain operable across restarts",
            "--external-reference",
            "WORK-CLI-1",
            "--constraint",
            "local prototype only",
            "--max-turns",
            "12",
            "--wall-clock-seconds",
            "300",
            "--decompose",
        )
        self.assertEqual(mission["external_reference"], "WORK-CLI-1")
        self.assertEqual(mission["status"], "decomposed")
        self.assertEqual(mission["budget"]["turns_remaining"], 12)
        self.assertLessEqual(mission["budget"]["wall_clock_seconds_remaining"], 300)

        shown = self.cli(
            "--root",
            str(self.root),
            "show",
            "--external-reference",
            "WORK-CLI-1",
        )
        self.assertEqual(shown["mission_id"], mission["mission_id"])
        self.assertEqual(shown["brief"]["objective"], "Implement a durable operational surface")

        missions = self.cli(
            "--root",
            str(self.root),
            "missions",
            "--external-reference",
            "WORK-CLI-1",
        )
        self.assertEqual(len(missions), 1)

        events = self.cli(
            "--root",
            str(self.root),
            "events",
            "--mission-id",
            mission["mission_id"],
            "--limit",
            "2",
        )
        self.assertEqual(len(events), 2)
        self.assertEqual([event["sequence"] for event in events], [3, 4])

        product_root = self.root / "product"
        product_root.mkdir()
        (product_root / "learning.jsonl").write_text(
            '{"type":"fixture","api_key":"must-redact"}\n'
        )
        product = self.cli("--root", str(self.root), "product")
        self.assertEqual(product["recent_learning"][0]["api_key"], "REDACTED")
        self.assertEqual(product["traffic_count"], 0)

    def test_show_missing_mission_fails_closed(self) -> None:
        output = io.StringIO()
        result = main(
            [
                "--root",
                str(self.root),
                "show",
                "--external-reference",
                "MISSING",
            ],
            stdout=output,
        )
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())["error"], "mission_not_found")
