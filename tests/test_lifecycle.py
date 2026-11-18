from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

from asdi.lifecycle import (
    CommandAgent,
    LifecycleStore,
    MergeAuthorization,
    MissionGuardrails,
    MissionEngine,
    ProductOps,
    ensure_local_target,
)
from scripts.run_company_scenarios import CompanyRun


ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "scripts" / "fixture_agent.py"
REVIEWER = ROOT / "scripts" / "fixture_reviewer.py"
AUTHORIZATION = MergeAuthorization(
    approver="test_owner",
    decision_reference="lifecycle integration regression",
    authority="T0_human",
)


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.run = CompanyRun(self.root, AGENT, REVIEWER)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_merge_authority_cannot_be_autonomous(self) -> None:
        with self.assertRaises(ValueError):
            MergeAuthorization(
                approver="engine",
                decision_reference="not allowed",
                authority="autonomous",
            ).validated()

    def test_command_agent_adapter_is_shell_free_and_charges_one_turn(self) -> None:
        agent = CommandAgent(
            name="compatibility_fixture",
            argv=(
                sys.executable,
                str(AGENT),
                "--workspace",
                "{workspace}",
                "--mission-id",
                "{mission_id}",
                "--variant",
                "{variant}",
            ),
            timeout_seconds=5,
        )
        mission = self.run.store.create_mission(
            objective="command adapter fixture",
            why="verify explicit argv adapter compatibility",
            constraints=[],
            mission_kind="feature",
            guardrails=MissionGuardrails(max_turns=8, max_spend_usd=1, wall_clock_seconds=60),
        )
        mission_id = mission["mission_id"]
        self.run.engine.decompose(mission_id)
        self.run.engine.execute_agent(mission_id, agent=agent, variant="good")
        state = self.run.store.load(mission_id)
        self.assertEqual(state["budget"]["turns_used"], 1)
        self.assertTrue(
            (self.run.store.mission_root(mission_id) / "workspace" / "app.py").is_file()
        )

    def test_turn_guardrail_blocks_the_next_mission_turn(self) -> None:
        mission = self.run.store.create_mission(
            objective="turn guardrail fixture",
            why="verify autonomous execution cannot exceed its budget",
            constraints=[],
            mission_kind="feature",
            guardrails=MissionGuardrails(max_turns=1, max_spend_usd=1, wall_clock_seconds=60),
        )
        mission_id = mission["mission_id"]
        self.run.engine.decompose(mission_id)
        self.run.engine.execute_agent(mission_id, agent_path=AGENT, variant="good")
        with self.assertRaisesRegex(RuntimeError, "mission guardrail exceeded: max_turns"):
            self.run.engine.self_verify(
                mission_id,
                app_path=self.run.store.mission_root(mission_id) / "workspace" / "app.py",
            )
        state = self.run.store.load(mission_id)
        self.assertEqual(state["status"], "guardrail_exceeded")
        self.assertEqual(state["budget"]["turns_used"], 1)

    def test_spend_guardrail_blocks_completion_after_reported_cost(self) -> None:
        agent = CommandAgent(
            name="cost_fixture",
            argv=(
                sys.executable,
                str(AGENT),
                "--workspace",
                "{workspace}",
                "--mission-id",
                "{mission_id}",
                "--variant",
                "{variant}",
            ),
            timeout_seconds=5,
            default_cost_usd=2.0,
        )
        mission = self.run.store.create_mission(
            objective="spend guardrail fixture",
            why="verify reported cost is charged and enforced",
            constraints=[],
            mission_kind="feature",
            guardrails=MissionGuardrails(max_turns=8, max_spend_usd=1, wall_clock_seconds=60),
        )
        mission_id = mission["mission_id"]
        self.run.engine.decompose(mission_id)
        with self.assertRaisesRegex(RuntimeError, "mission guardrail exceeded: max_spend_usd"):
            self.run.engine.execute_agent(mission_id, agent=agent, variant="good")
        state = self.run.store.load(mission_id)
        self.assertEqual(state["status"], "guardrail_exceeded")
        self.assertGreaterEqual(state["budget"]["spend_usd"], 2.0)

    def test_elapsed_wall_clock_blocks_agent_execution(self) -> None:
        mission = self.run.store.create_mission(
            objective="wall-clock guardrail fixture",
            why="verify mission age is enforced before execution",
            constraints=[],
            mission_kind="feature",
            guardrails=MissionGuardrails(max_turns=8, max_spend_usd=1, wall_clock_seconds=10),
        )
        mission_id = mission["mission_id"]
        self.run.engine.decompose(mission_id)
        state = self.run.store.load(mission_id)
        state["budget"]["wall_clock_started_at"] -= 20
        self.run.store._save(state)
        with self.assertRaisesRegex(RuntimeError, "mission guardrail exceeded: wall_clock_seconds"):
            self.run.engine.execute_agent(mission_id, agent_path=AGENT, variant="good")
        self.assertEqual(self.run.store.load(mission_id)["status"], "guardrail_exceeded")

    def test_external_reference_is_queryable_across_resets(self) -> None:
        reference = "WORK-RESET-1"
        first = self.run.store.create_mission(
            objective="bounded reset fixture",
            why="verify failed missions receive a fresh brief-v2 context",
            constraints=[],
            mission_kind="repair",
            external_reference=reference,
            guardrails=MissionGuardrails(max_turns=100, max_spend_usd=1, wall_clock_seconds=60),
        )
        self.assertEqual(first["reset_generation"], 1)
        mission_id = first["mission_id"]
        self.run.engine.decompose(mission_id)
        for _ in range(3):
            try:
                self.run.engine.repair(mission_id, agent_path=AGENT, findings=[])
            except RuntimeError:
                pass
        exhausted = self.run.store.load(mission_id)
        self.assertEqual(exhausted["status"], "reset_required")
        reset = self.run.engine.reset(mission_id, reset_reason="two failed repair attempts")
        self.assertEqual(reset["reset_generation"], 2)
        self.assertEqual(reset["external_reference"], reference)
        self.assertEqual(reset["parent_mission_id"], mission_id)
        self.assertEqual(reset["repair_attempts"], 0)
        self.assertEqual(self.run.store.load(mission_id)["status"], "reset_created")
        matches = self.run.store.find_by_external_reference(reference)
        self.assertEqual([item["mission_id"] for item in matches], [mission_id, reset["mission_id"]])

    def test_reset_rejects_active_missions(self) -> None:
        mission = self.run.store.create_mission(
            objective="active reset guard",
            why="reset must not discard active work",
            constraints=[],
            mission_kind="feature",
        )
        with self.assertRaises(ValueError):
            self.run.engine.reset(mission["mission_id"], reset_reason="not exhausted")

    def test_product_lifecycle_passes_with_t0_local_merge(self) -> None:
        evidence = self.run.product_lifecycle()
        self.assertEqual(evidence["status"], "experiment_completed")
        self.assertTrue(all(task["status"] == "completed" for task in evidence["tasks"]))
        self.assertFalse(evidence["classification"]["autonomous_merge_authorized"])
        self.assertFalse(evidence["merge"]["remote_merge"])
        self.assertTrue(evidence["merge"]["local_commit"])
        self.assertEqual(evidence["default_flag_response"]["response"]["variant"], "off")
        self.assertEqual(evidence["experiment_verdict"]["verdict"], "keep_for_human_review")
        report = self.run.store.load(evidence["mission_id"])
        sequences = [event["sequence"] for event in self.run.store.events(evidence["mission_id"])]
        self.assertEqual(sequences, list(range(1, len(sequences) + 1)))
        self.assertTrue((self.run.product.current_app()).is_file())
        self.assertGreater(len(report["artifacts"]), 0)

    def test_self_healing_lifecycle_detects_repairs_and_closes(self) -> None:
        # Deploy the known-good baseline first, then create a controlled defect.
        self.run.product_lifecycle()
        evidence = self.run.self_healing_lifecycle()
        self.assertTrue(evidence["detection"]["healthy"] is False)
        self.assertTrue(evidence["defect"]["defect_id"])
        self.assertEqual(evidence["repair_status"], "production_verified")
        self.assertTrue(all(task["status"] == "completed" for task in evidence["repair_tasks"]))
        self.assertEqual(evidence["production_verification"]["closure"], "closed_verified")
        self.assertFalse(evidence["closure"]["reopened"])

    def test_local_product_ops_rollback(self) -> None:
        store = LifecycleStore(self.root)
        engine = MissionEngine(store)
        mission = store.create_mission(
            objective="rollback fixture",
            why="verify local deployment rollback",
            constraints=[],
            mission_kind="feature",
        )
        mission_id = mission["mission_id"]
        engine.decompose(mission_id)
        engine.execute_agent(mission_id, agent_path=AGENT, variant="good")
        workspace = store.mission_root(mission_id) / "workspace"
        self.run.product.deploy(mission_id, workspace)
        first = self.run.product.current_app().resolve()
        engine.execute_agent(mission_id, agent_path=AGENT, variant="good")
        self.run.product.deploy(mission_id, workspace)
        second = self.run.product.current_app().resolve()
        self.assertNotEqual(first, second)
        rollback = self.run.product.rollback(reason="integration regression test")
        self.assertEqual(rollback["reason"], "integration regression test")
        self.assertEqual(self.run.product.current_app().resolve(), first)
        self.assertTrue(ensure_local_target(self.root / "target").exists())
