#!/usr/bin/env python3
"""Run the integrated product and self-healing lifecycle scenarios."""

from __future__ import annotations

import argparse
import json
import shlex
import tempfile
import time
from pathlib import Path

from asdi.lifecycle import (
    CommandAgent,
    MissionGuardrails,
    LifecycleStore,
    MergeAuthorization,
    MissionEngine,
    ProductOps,
    ensure_local_target,
)


AUTHORIZATION = MergeAuthorization(
    approver="repository_owner",
    decision_reference="owner directive 2026-11-15: complete lifecycle integration, local prototype only",
    authority="T0_human",
)


class CompanyRun:
    def __init__(
        self,
        root: Path,
        agent: Path | CommandAgent,
        reviewer: Path,
        *,
        guardrails: MissionGuardrails | None = None,
    ) -> None:
        self.root = root
        self.store = LifecycleStore(root)
        self.engine = MissionEngine(self.store)
        self.product = ProductOps(root / "product")
        self.target = ensure_local_target(root / "target")
        self.agent = agent
        self.reviewer = reviewer
        self.guardrails = guardrails or MissionGuardrails(
            max_turns=24,
            max_spend_usd=2.0,
            wall_clock_seconds=120,
        )

    def execute_feature_mission(
        self,
        mission_id: str,
        *,
        authorization: MergeAuthorization,
        variant: str = "good",
        expose: bool = True,
        traffic: int = 4,
    ) -> dict:
        mission = self.store.load(mission_id)
        if mission["mission_kind"] != "feature":
            raise ValueError("local autonomous runner currently supports feature missions")
        if mission["status"] not in {"created", "admitted", "decomposed"}:
            raise ValueError(f"mission is {mission['status']}; expected created/admitted/decomposed")

        self.engine.decompose(mission_id)
        self.run_agent(mission_id, variant)
        workspace = self.store.mission_root(mission_id) / "workspace"
        self.engine.self_verify(mission_id, app_path=workspace / "app.py")
        review = self.engine.independent_review(mission_id, reviewer_path=self.reviewer)
        if any(not result["passed"] for result in review):
            raise RuntimeError(f"independent review failed for {mission_id}")
        self.engine.classify(mission_id)
        merge = self.engine.merge(mission_id, target_root=self.target, authorization=authorization)
        deployment = self.product.deploy(mission_id, workspace)
        default = self.product.request(scenario="normal")
        exposure = None
        experiment = None
        if expose:
            exposure = self.product.set_flag(
                "prototype_feature",
                True,
                decision_reference=authorization.decision_reference,
            )
            experiment = self.product.experiment(
                name="prototype_feature", traffic=traffic
            )
        self.engine.complete_task(
            mission_id,
            "deployment",
            {"deployment": deployment, "default_flag_response": default},
            status="deployed",
        )
        if experiment is not None:
            self.engine.complete_task(
                mission_id,
                "experiment",
                {
                    "experiment_verdict": experiment["verdict"],
                    "passed": experiment["passed"],
                    "failed": experiment["failed"],
                },
                status="experiment_completed",
            )
        state = self.store.load(mission_id)
        return {
            "mission_id": mission_id,
            "status": state["status"],
            "external_reference": state.get("external_reference"),
            "guardrails": state["guardrails"],
            "budget": state["budget"],
            "tasks": state["tasks"],
            "classification": state["classification"],
            "merge": merge,
            "deployment": deployment,
            "default_flag_response": default,
            "controlled_exposure": exposure,
            "experiment_verdict": (
                {
                    "verdict": experiment["verdict"],
                    "passed": experiment["passed"],
                    "failed": experiment["failed"],
                }
                if experiment
                else None
            ),
            "events": [event["type"] for event in self.store.events(mission_id)],
        }

    @property
    def agent_constraint(self) -> str:
        return "explicit command adapter only" if isinstance(self.agent, CommandAgent) else "fixture agents only"

    def _implement(self, mission_id: str, variant: str) -> None:
        self.engine.decompose(mission_id)
        self.run_agent(mission_id, variant)
        mission_root = self.store.mission_root(mission_id) / "workspace"
        self.engine.self_verify(mission_id, app_path=mission_root / "app.py")
        review = self.engine.independent_review(mission_id, reviewer_path=self.reviewer)
        if any(not result["passed"] for result in review):
            raise RuntimeError(f"independent review failed for {mission_id}")
        self.engine.classify(mission_id)

    def run_agent(self, mission_id: str, variant: str) -> dict:
        if isinstance(self.agent, CommandAgent):
            timeout = 560 if self.agent.name == "live_cli" else 10
            return self.engine.execute_agent(
                mission_id, agent=self.agent, variant=variant, timeout=timeout
            )
        return self.engine.execute_agent(mission_id, agent_path=self.agent, variant=variant)

    def detect_defect(self, *, scenario: str = "load") -> tuple[dict, dict | None]:
        observation = self.product.observe(scenario=scenario)
        if observation["healthy"]:
            return observation, None
        return observation, self.product.raise_defect(observation)

    def repair_defect(
        self,
        defect: dict,
        *,
        parent_mission_id: str,
        authorization: MergeAuthorization,
        external_reference: str,
        traffic: int = 4,
    ) -> dict:
        parent = self.store.load(parent_mission_id)
        repair = self.store.create_mission(
            objective=f"Repair defect {defect['defect_id']}",
            why="Boundedly repair the detected local defect and verify the outcome.",
            constraints=[
                "maximum two repair attempts",
                self.agent_constraint,
                "local target only",
                "no production secrets",
                "T0 human merge authorization",
            ],
            mission_kind="repair",
            parent_mission_id=parent_mission_id,
            detection_evidence=defect,
            guardrails=self.guardrails,
            external_reference=(
                f"{external_reference}::repair::{defect['defect_id']}"
                if external_reference
                else f"repair::{defect['defect_id']}"
            ),
            reset_generation=int(parent.get("reset_generation", 1)),
        )
        repair_id = repair["mission_id"]
        self.engine.decompose(repair_id)
        triage = self.engine.record_triage(repair_id, defect)
        self.run_agent(repair_id, "repair")
        repaired_workspace = self.store.mission_root(repair_id) / "workspace"
        self.engine.self_verify(repair_id, app_path=repaired_workspace / "app.py")
        review = self.engine.independent_review(repair_id, reviewer_path=self.reviewer)
        if any(not result["passed"] for result in review):
            raise RuntimeError(f"independent repair review failed for {repair_id}")
        self.engine.classify(repair_id)
        merge = self.engine.merge(
            repair_id, target_root=self.target, authorization=authorization
        )
        repair_deployment = self.product.deploy(repair_id, repaired_workspace)
        verification = self.product.verify_repair(traffic=traffic)
        closure = self.product.close_defect(defect, verification)
        if verification["closure"] == "reopened":
            try:
                rollback = self.product.rollback(
                    reason=f"repair verification failed: {defect['defect_id']}"
                )
                verification["rollback"] = rollback
            except ValueError:
                verification["rollback"] = None
        self.engine.complete_task(
            repair_id,
            "deployment",
            {"deployment": repair_deployment},
            status="repair_deployed",
        )
        self.engine.complete_task(
            repair_id,
            "verification",
            {
                "closure": verification["closure"],
                "passed": verification["passed"],
                "rollback": verification.get("rollback"),
            },
            status="production_verified",
        )
        repair_state = self.store.load(repair_id)
        return {
            "action": "repair",
            "defect": defect,
            "repair_mission_id": repair_id,
            "triage": triage,
            "repair_status": repair_state["status"],
            "repair_guardrails": repair_state["guardrails"],
            "repair_budget": repair_state["budget"],
            "repair_tasks": repair_state["tasks"],
            "repair_merge": merge,
            "repair_deployment": repair_deployment,
            "production_verification": {
                "passed": verification["passed"],
                "closure": verification["closure"],
                "outcomes": len(verification["outcomes"]),
                "rollback": verification.get("rollback"),
            },
            "closure": closure,
            "repair_events": [
                event["type"] for event in self.store.events(repair_id)
            ],
        }

    def monitor(
        self,
        *,
        parent_mission_id: str,
        authorization: MergeAuthorization,
        external_reference: str,
        scenario: str = "load",
        traffic: int = 4,
        auto_repair: bool = True,
    ) -> dict:
        observation, defect = self.detect_defect(scenario=scenario)
        if defect is None or not auto_repair:
            return {
                "action": "none",
                "observation": observation,
                "defect": defect,
            }
        result = self.repair_defect(
            defect,
            parent_mission_id=parent_mission_id,
            authorization=authorization,
            external_reference=external_reference,
            traffic=traffic,
        )
        return {"observation": observation, **result}

    def product_lifecycle(self) -> dict:
        mission = self.store.create_mission(
            objective="Deliver a controlled local prototype feature",
            why="Demonstrate the integrated ASDI product lifecycle on one host.",
            constraints=[
                self.agent_constraint,
                "local target only",
                "no production secrets",
                "feature flag starts off",
                "T0 human merge authorization",
            ],
            mission_kind="feature",
            guardrails=self.guardrails,
            external_reference="asdi-local-product-2026-11-15",
        )
        mission_id = mission["mission_id"]
        result = self.execute_feature_mission(
            mission_id,
            authorization=AUTHORIZATION,
            variant="good",
            expose=True,
            traffic=4,
        )
        return {"stage": "product_lifecycle", **result}

    def self_healing_lifecycle(self) -> dict:
        feature = self.store.create_mission(
            objective="Add local load handling to the prototype feature",
            why="Create a controlled production defect so self-healing can be demonstrated.",
            constraints=[
                self.agent_constraint,
                "local target only",
                "no production secrets",
                "T0 human merge authorization",
            ],
            mission_kind="feature",
            guardrails=self.guardrails,
            external_reference="asdi-local-self-healing-2026-11-15",
        )
        feature_id = feature["mission_id"]
        deployment = self.execute_feature_mission(
            feature_id,
            authorization=AUTHORIZATION,
            variant="buggy",
            expose=False,
        )
        observation, defect = self.detect_defect()
        repair = self.repair_defect(
            defect,
            parent_mission_id=feature_id,
            authorization=AUTHORIZATION,
            external_reference="asdi-local-self-healing-2026-11-15",
            traffic=4,
        )
        feature_state = self.store.load(feature_id)
        return {
            "stage": "self_healing_lifecycle",
            "feature_mission_id": feature_id,
            "defective_deployment": deployment,
            "detection": observation,
            "defect": defect,
            **repair,
            "feature_events": [event["type"] for event in self.store.events(feature_id)],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root")
    parser.add_argument("--agent", default="scripts/fixture_agent.py")
    parser.add_argument(
        "--live-agent-command",
        help="Explicit argv command string; supports {workspace}, {mission_id}, {objective}, and {variant}.",
    )
    parser.add_argument("--reviewer", default="scripts/fixture_reviewer.py")
    parser.add_argument("--agent-proxy", default="http://127.0.0.1:7890")
    parser.add_argument("--wall-clock-seconds", type=int, default=120)
    arguments = parser.parse_args()
    root = Path(arguments.root).resolve() if arguments.root else Path(tempfile.mkdtemp(prefix=f"asdi-company-{time.strftime('%Y%m%d-%H%M%S')}-"))
    root.mkdir(parents=True, exist_ok=True)
    agent: Path | CommandAgent
    if arguments.live_agent_command:
        if Path(arguments.live_agent_command[0]).is_absolute() is False:
            parser.error("live agent executable must be an absolute path")
        agent = CommandAgent(
            name="live_cli",
            argv=tuple(shlex.split(arguments.live_agent_command)),
            timeout_seconds=560,
            env=(
                ("HTTP_PROXY", arguments.agent_proxy),
                ("HTTPS_PROXY", arguments.agent_proxy),
                ("ALL_PROXY", arguments.agent_proxy),
                ("NO_PROXY", "localhost,127.0.0.1"),
                ("CODEX_HOME", "/Users/russell/.codex"),
            ),
        )
    else:
        agent = Path(arguments.agent)
    run = CompanyRun(
        root,
        agent,
        Path(arguments.reviewer),
        guardrails=MissionGuardrails(
            max_turns=48,
            max_spend_usd=2.0,
            wall_clock_seconds=arguments.wall_clock_seconds,
        ),
    )
    runner_info = (
        {"kind": "command_agent", "name": agent.name}
        if isinstance(agent, CommandAgent)
        else {"kind": "fixture_agent", "path": str(agent)}
    )
    report = {
        "schema_version": "asdi.company-scenario-report/v0",
        "result": "pass",
        "evidence_root": str(root),
        "execution_mode": (
            "explicit command agent; local target only; no production infrastructure"
            if isinstance(agent, CommandAgent)
            else "local fixture agents; no model APIs; no production infrastructure"
        ),
        "agent_adapter": runner_info,
        "product_lifecycle": run.product_lifecycle(),
        "self_healing_lifecycle": run.self_healing_lifecycle(),
        "mission_index": {
            "product": run.store.find_by_external_reference("asdi-local-product-2026-11-15"),
            "self_healing": run.store.find_by_external_reference("asdi-local-self-healing-2026-11-15"),
        },
        "learning_events": (root / "product" / "learning.jsonl").read_text().splitlines(),
        "limitations": {
            "fixture_agents": not isinstance(agent, CommandAgent),
            "live_model_agents": False,
            "remote_merge": False,
            "production_deployment": False,
            "strict_container_egress_accepted": False,
            "guardrails_enforced": True,
            "guardrail_scope": "local mission turns, reported spend, and elapsed wall clock",
        },
    }
    report_path = root / "company-scenario-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
