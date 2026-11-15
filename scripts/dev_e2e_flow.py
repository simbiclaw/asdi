#!/usr/bin/env python3
"""Run an explicit, noncompliant, development-only container flow.

This is not ASDI-012 acceptance evidence.  It uses a Docker bridge and
requires an owner-approved ``development_open`` run contract so the launcher,
durable evidence, done-check, cancellation, cleanup, and human-review handoff
can be exercised before the strict egress transport is selected.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from asdi.runtime import CodexAdapter, RunLauncher, RunStore, RuntimeAdapterConfig
from asdi.run_contract import build_run_contract, validate_run_contract
from asdi.sandbox import SandboxSpec


AGENT_FIXTURE = '''\
import json
import sys
import urllib.request
from pathlib import Path

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read(512).decode("utf-8", errors="replace")
    network = {"ok": True, "url": url, "status": response.status, "prefix": body[:80]}
except Exception as error:
    Path("network-error.txt").write_text(f"{type(error).__name__}: {error}\\n")
    raise

Path("agent-output.json").write_text(
    json.dumps({"ok": True, "network": network}, indent=2) + "\\n"
)
print(json.dumps({"type": "result", "usage": {"usd_cost": 0.0, "turns": 1}}))
'''

VERIFY_FIXTURE = '''\
import json
from pathlib import Path

value = json.loads(Path("/workspace/agent-output.json").read_text())
assert value["ok"] is True
assert value["network"]["ok"] is True
print("development-flow-done-check-ok")
'''

SLEEP_FIXTURE = '''\
import time

print("development-flow-cancellation-started", flush=True)
time.sleep(30)
'''


def development_contract(url: str) -> dict[str, Any]:
    value = build_run_contract(
        objective="Exercise the development-only ASDI container flow",
        why="Owner asked to complete the flow before selecting strict egress enforcement.",
        constraints=[
            "development only",
            "no production credentials or production data",
            "no irreversible actions",
        ],
        out_of_scope=["board integration", "merge", "deployment", "production access"],
        done_check={
            "description": "Verify the isolated fixture artifact.",
            "argv": ["python3", "/workspace/verify_flow.py"],
        },
        human_provided=["objective", "why"],
        lead_agent_authored=["constraints", "out_of_scope", "done_check"],
        task_type="spike",
    )
    value["boundaries"]["network"] = {
        "mode": "development_open",
        "allowlist": [],
        "override_reason": "owner_approved",
        "override_reference": "owner-2026-11-15-dev-flow-first",
        "scope": "development_only",
    }
    validate_run_contract(value)
    return value


def cancellation_contract() -> dict[str, Any]:
    value = development_contract("https://example.com/")
    value["done_check"] = {
        "description": "Unreachable because the run is cancelled.",
        "argv": ["python3", "/workspace/verify_flow.py"],
    }
    validate_run_contract(value)
    return value


def docker_inspect(name: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["docker", "container", "inspect", name],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return {"inspect_available": True, "state": "present"}
    return {"inspect_available": False, "state": "absent"}


def run_success(
    launcher: RunLauncher,
    store: RunStore,
    evidence_root: Path,
    image: str,
    url: str,
) -> dict[str, Any]:
    contract = development_contract(url)
    created = launcher.create_run(contract, board_task_reference="dev-e2e-success")
    run_id = created["run_id"]
    workspace = store.run_root(run_id) / "workspace"
    (workspace / "agent_fixture.py").write_text(AGENT_FIXTURE)
    (workspace / "verify_flow.py").write_text(VERIFY_FIXTURE)

    handle = launcher.start_runtime(
        run_id,
        CodexAdapter.name,
        RuntimeAdapterConfig(
            executable_path="/usr/bin/python3",
            container_executable_path="/usr/bin/python3",
            argv_prefix=("/workspace/agent_fixture.py", url),
            include_objective=False,
        ),
        isolation_mode="container",
        allow_noncompliant_test=True,
        sandbox_spec=SandboxSpec(
            image=image,
            runtime_executable="/usr/bin/python3",
            network_profile="development_open",
        ),
    )
    final = handle.wait(timeout=30)
    events = store.events(run_id)
    return {
        "stage": "execution_and_self_verification",
        "run_id": run_id,
        "status": final["status"],
        "isolation_compliant": final["isolation_compliant"],
        "isolation_mode": final["isolation_mode"],
        "network_mode": final["sandbox"]["network_mode"],
        "container_id": final["process"].get("container_id"),
        "done_check": final["done_check"],
        "usage": final["usage"],
        "stdout": (store.run_root(run_id) / "stdout.log").read_text(),
        "agent_output": json.loads((workspace / "agent-output.json").read_text()),
        "event_types": [event["type"] for event in events],
        "event_sequences": [event["sequence"] for event in events],
    }


def run_cancellation(
    launcher: RunLauncher,
    store: RunStore,
    image: str,
) -> dict[str, Any]:
    contract = cancellation_contract()
    created = launcher.create_run(contract, board_task_reference="dev-e2e-cancel")
    run_id = created["run_id"]
    (store.run_root(run_id) / "workspace" / "sleep_fixture.py").write_text(SLEEP_FIXTURE)
    handle = launcher.start_runtime(
        run_id,
        CodexAdapter.name,
        RuntimeAdapterConfig(
            executable_path="/usr/bin/python3",
            container_executable_path="/usr/bin/python3",
            argv_prefix=("/workspace/sleep_fixture.py",),
            include_objective=False,
        ),
        isolation_mode="container",
        allow_noncompliant_test=True,
        sandbox_spec=SandboxSpec(
            image=image,
            runtime_executable="/usr/bin/python3",
            network_profile="development_open",
        ),
    )
    time.sleep(0.5)
    container_name = f"asdi-{run_id}"
    before = docker_inspect(container_name)
    final = handle.cancel(timeout=10)
    after = docker_inspect(container_name)
    return {
        "stage": "cancellation_and_cleanup",
        "run_id": run_id,
        "status": final["status"],
        "signal": final["result"].get("signal"),
        "container_before_cancel": before,
        "container_after_cancel": after,
        "container_cleaned_event": any(
            event["type"] == "container_cleaned" for event in store.events(run_id)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="safeclaw:cc-2.1.283")
    parser.add_argument("--url", default="https://example.com/")
    parser.add_argument("--evidence-root")
    arguments = parser.parse_args()

    root = (
        Path(arguments.evidence_root).resolve()
        if arguments.evidence_root
        else Path(tempfile.mkdtemp(prefix=f"asdi-dev-flow-{time.strftime('%Y%m%d-%H%M%S')}-"))
    )
    store = RunStore(root)
    launcher = RunLauncher(store)

    success = run_success(launcher, store, root, arguments.image, arguments.url)
    cancellation = run_cancellation(launcher, store, arguments.image)
    success_run_id = success["run_id"]
    contract = store.load_run(success_run_id)["contract"]

    report = {
        "schema_version": "asdi.development-flow-report/v0",
        "result": (
            "development_flow_pass"
            if success["status"] == "succeeded"
            and cancellation["status"] == "cancelled"
            and cancellation["container_cleaned_event"]
            else "development_flow_fail"
        ),
        "compliance": {
            "autonomous_acceptance": False,
            "isolation_compliant": False,
            "network_profile": "development_open_noncompliant",
            "production_authorized": False,
            "merge_authorized": False,
            "owner_override_reason": "owner_approved",
            "owner_override_reference": "owner-2026-11-15-dev-flow-first",
        },
        "admission": {
            "stage": "contract_validated",
            "run_id": success_run_id,
            "objective": contract["objective"],
            "network": contract["boundaries"]["network"],
            "guardrails": contract["guardrails"],
        },
        "success_run": success,
        "cancellation_run": cancellation,
        "limitations": {
            "guardrails_enforced": False,
            "board_integration": False,
            "independent_review_performed": False,
            "merge_performed": False,
            "asdi_012_accepted": False,
        },
    }
    report_path = root / "flow-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    review_packet = {
        "schema_version": "asdi.review-packet/v0",
        "run_id": success_run_id,
        "decision": "pending_human_review",
        "change_class": "development_fixture",
        "merge_authority": "T0_human",
        "autonomous_merge_authorized": False,
        "evidence": {
            "flow_report": str(report_path),
            "run_root": str(store.run_root(success_run_id)),
            "status": success["status"],
            "done_check_exit_code": success["done_check"]["exit_code"],
        },
        "policy_result": {
            "production_access": False,
            "irreversible_actions": False,
            "autonomous_merge": False,
            "network_compliance": "development_open_noncompliant",
        },
    }
    (root / "review-packet.json").write_text(
        json.dumps(review_packet, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["result"] == "development_flow_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
