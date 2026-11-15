from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.company_cli import main


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "scripts" / "fixture_agent.py"
REVIEWER = ROOT / "scripts" / "fixture_reviewer.py"


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

    def test_run_admitted_feature_through_governed_local_lifecycle(self) -> None:
        admitted = self.cli(
            "--root",
            str(self.root),
            "admit",
            "--objective",
            "Autonomously deliver a controlled local feature",
            "--why",
            "Verify durable CLI dispatch through the integrated lifecycle",
            "--external-reference",
            "WORK-RUN-1",
            "--max-turns",
            "24",
            "--max-spend-usd",
            "2",
            "--wall-clock-seconds",
            "300",
        )
        result = self.cli(
            "--root",
            str(self.root),
            "run",
            "--mission-id",
            admitted["mission_id"],
            "--agent",
            str(AGENT),
            "--reviewer",
            str(REVIEWER),
            "--approver",
            "test_owner",
            "--decision-reference",
            "explicit T0 local prototype regression",
            "--variant",
            "good",
            "--traffic",
            "4",
        )
        self.assertEqual(result["status"], "experiment_completed")
        self.assertTrue(all(task["status"] == "completed" for task in result["tasks"]))
        self.assertEqual(result["classification"]["change_class"], "T0_human")
        self.assertFalse(result["merge"]["autonomous_merge"])
        self.assertFalse(result["merge"]["remote_merge"])
        self.assertEqual(result["merge"]["authority"], "T0_human")
        self.assertEqual(result["default_flag_response"]["response"]["variant"], "off")
        self.assertEqual(result["experiment_verdict"]["verdict"], "keep_for_human_review")
        self.assertTrue(result["controlled_exposure"]["enabled"])
        self.assertEqual(result["budget"]["turns_used"], 5)

    def test_runner_can_deploy_without_exposure(self) -> None:
        admitted = self.cli(
            "--root",
            str(self.root),
            "admit",
            "--objective",
            "Deploy behind the default-off flag",
            "--why",
            "Controlled exposure must remain a separate decision",
            "--external-reference",
            "WORK-RUN-NO-EXPOSURE",
        )
        result = self.cli(
            "--root",
            str(self.root),
            "run",
            "--mission-id",
            admitted["mission_id"],
            "--agent",
            str(AGENT),
            "--reviewer",
            str(REVIEWER),
            "--approver",
            "test_owner",
            "--decision-reference",
            "deploy default-off only",
            "--no-exposure",
        )
        self.assertEqual(result["status"], "deployed")
        self.assertIsNone(result["controlled_exposure"])
        self.assertIsNone(result["experiment_verdict"])
        self.assertEqual(result["default_flag_response"]["response"]["variant"], "off")
