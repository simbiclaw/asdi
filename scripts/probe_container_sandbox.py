#!/usr/bin/env python3
"""Generate live ASDI-012 container-sandbox acceptance evidence."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from asdi.runtime import CodexAdapter, RunLauncher, RunStore, RuntimeAdapterConfig
from asdi.sandbox import SandboxSpec
from tests.test_run_launcher import synthetic_contract


IMAGE = "safeclaw:cc-2.1.283"
def contract(allowlist: tuple[str, ...] = ()) -> dict[str, Any]:
    value = synthetic_contract()
    value["done_check"]["argv"] = ["/usr/bin/python3", "--version"]
    mode = "allowlist" if allowlist else "deny_all"
    value["boundaries"]["network"] = {
        "mode": mode,
        "allowlist": list(allowlist),
    }
    return value


def config(prefix: tuple[str, ...], suffix: tuple[str, ...] = ()) -> RuntimeAdapterConfig:
    return RuntimeAdapterConfig(
        executable_path="/usr/bin/perl",
        container_executable_path="/usr/bin/perl",
        argv_prefix=prefix,
        argv_suffix=suffix,
        include_objective=False,
    )


def docker(*arguments: str) -> str:
    completed = subprocess.run(
        ["docker", *arguments], check=False, capture_output=True, text=True
    )
    return completed.stdout


def main() -> None:
    evidence_root = Path(
        tempfile.mkdtemp(prefix=f"asdi-gate-012-{time.strftime('%Y%m%d-%H%M%S')}-")
    )
    store = RunStore(evidence_root)
    launcher = RunLauncher(store)
    report: dict[str, Any] = {"evidence_root": str(evidence_root), "image": IMAGE}

    created = launcher.create_run(contract(), board_task_reference="asdi-012-no-network")
    allowed_id = created["run_id"]
    handle = launcher.start_runtime(
        allowed_id,
        CodexAdapter.name,
        config(
            ("-e", "select(undef, undef, undef, 2); print \"container-no-network-ok\";"),
        ),
        isolation_mode="container",
        sandbox_spec=SandboxSpec(image=IMAGE, runtime_executable="/usr/bin/perl"),
    )
    final = handle.wait(timeout=30)
    report["allowed_run"] = {
        "run_id": allowed_id,
        "status": final["status"],
        "isolation_mode": final["isolation_mode"],
        "isolation_compliant": final["isolation_compliant"],
        "container_name": final["sandbox"]["container_name"],
        "container_id": final["process"].get("container_id"),
        "stdout": (store.run_root(allowed_id) / "stdout.log").read_text(),
        "network_mode": final["sandbox"]["network_mode"],
        "egress_mode": final["sandbox"]["egress_mode"],
        "egress_decisions": [],
        "done_check": final["done_check"],
    }

    cancelled_created = launcher.create_run(contract(), board_task_reference="asdi-012-cancel")
    cancelled_id = cancelled_created["run_id"]
    cancelled = launcher.start_runtime(
        cancelled_id,
        CodexAdapter.name,
        config(("-e", "print \"running\"; sleep 30;")),
        isolation_mode="container",
        sandbox_spec=SandboxSpec(image=IMAGE, runtime_executable="/usr/bin/perl"),
    )
    cancelled_name = f"asdi-{cancelled_id}"
    before_cancel = docker("container", "inspect", cancelled_name, "--format", "{{.State.Running}}").strip()
    final_cancelled = cancelled.cancel(timeout=10)
    after_cancel = docker("container", "inspect", cancelled_name, "--format", "{{.State.Running}}")
    report["cancelled_run"] = {
        "run_id": cancelled_id,
        "status": final_cancelled["status"],
        "signal": final_cancelled["result"].get("signal"),
        "container_running_before_cancel": before_cancel,
        "container_inspect_after_cancel": after_cancel.strip(),
        "container_cleaned_event": any(
            event["type"] == "container_cleaned" for event in store.events(cancelled_id)
        ),
    }

    concurrent_ids: list[str] = []
    concurrent_handles = []
    concurrent_mounts: dict[str, str] = {}
    for index in range(2):
        item = launcher.create_run(contract(), board_task_reference=f"asdi-012-concurrent-{index}")
        run_id = item["run_id"]
        writer = (
            "/workspace/write_marker.pl",
            str(index),
        )
        writer_path = store.run_root(run_id) / "workspace" / "write_marker.pl"
        writer_path.write_text(
            "use strict;\nuse warnings;\n"
            "$| = 1;\n"
            "print \"started\";\n"
            "select(undef, undef, undef, 5);\n"
            "open(my $fh, '>', '/workspace/marker.txt') or die $!;\n"
            "print {$fh} \"run-$ARGV[0]\" . chr(10);\n"
            "close $fh;\n"
            "open(my $in, '<', '/workspace/marker.txt') or die $!;\n"
            "while (my $line = <$in>) { print $line; }\n"
        )
        concurrent_handles.append(
            launcher.start_runtime(
                run_id,
                CodexAdapter.name,
                config(writer, (str(index),)),
                isolation_mode="container",
                sandbox_spec=SandboxSpec(image=IMAGE, runtime_executable="/usr/bin/perl"),
            )
        )
        concurrent_ids.append(run_id)
    for run_id in concurrent_ids:
        deadline = time.monotonic() + 5
        while "true" not in docker(
            "container", "inspect", f"asdi-{run_id}", "--format", "{{.State.Running}}"
        ):
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        concurrent_mounts[run_id] = docker(
            "container",
            "inspect",
            f"asdi-{run_id}",
            "--format",
            "{{json .Mounts}}",
        )
    for process_handle in concurrent_handles:
        process_handle.wait(timeout=15)
    concurrent_results = []
    for index, run_id in enumerate(concurrent_ids):
        own = store.run_root(run_id) / "workspace" / "marker.txt"
        other_index = 1 - index
        other = store.run_root(concurrent_ids[other_index]) / "workspace" / "marker.txt"
        mounts = concurrent_mounts[run_id]
        concurrent_results.append(
            {
                "run_id": run_id,
                "own_marker": own.read_text().strip(),
                "other_host_workspace_marker_exists": other.exists(),
                "mounts": mounts,
            }
        )
    report["concurrent_runs"] = concurrent_results

    env_created = launcher.create_run(contract(), board_task_reference="asdi-012-env")
    env_id = env_created["run_id"]
    os.environ["ASDI_SECRET"] = "do-not-inherit"
    try:
        env_handle = launcher.start_runtime(
            env_id,
            CodexAdapter.name,
            config(("-e", "print \"$_=\" . $ENV{$_} . chr(10) foreach keys %ENV;")),
            isolation_mode="container",
            sandbox_spec=SandboxSpec(image=IMAGE, runtime_executable="/usr/bin/perl"),
        )
    finally:
        os.environ.pop("ASDI_SECRET", None)
    env_final = env_handle.wait(timeout=15)
    env_output = (store.run_root(env_id) / "stdout.log").read_text()
    report["environment_run"] = {
        "run_id": env_id,
        "status": env_final["status"],
        "inherited_secret_visible": "ASDI_SECRET" in env_output,
        "explicit_asdi_run_id_visible": env_id in env_output,
        "output_keys": sorted(line.split("=", 1)[0] for line in env_output.splitlines() if "=" in line),
    }

    failure_created = launcher.create_run(contract(), board_task_reference="asdi-012-setup-failure")
    failure_id = failure_created["run_id"]
    setup_error = None
    try:
        launcher.start_runtime(
            failure_id,
            CodexAdapter.name,
            config(("-e", "print 'unreachable';")),
            isolation_mode="container",
            sandbox_spec=SandboxSpec(image="asdi-missing-image:do-not-pull", runtime_executable="/usr/bin/perl"),
        )
    except RuntimeError as error:
        setup_error = str(error)
    failure_state = store.load_run(failure_id)
    report["setup_failure_run"] = {
        "run_id": failure_id,
        "status": failure_state["status"],
        "reason": failure_state["result"]["reason"],
        "error": setup_error,
    }

    report["post_run_containers"] = {
        run_id: docker("container", "inspect", f"asdi-{run_id}", "--format", "{{.State.Running}}").strip()
        for run_id in [allowed_id, cancelled_id, env_id, failure_id, *concurrent_ids]
    }
    report["result"] = (
        "pass"
        if (
            report["allowed_run"]["status"] == "succeeded"
            and len(report["allowed_run"]["egress_decisions"]) >= 2
            and report["allowed_run"]["egress_decisions"][0]["reason"].startswith("private_destination_forbidden")
            and report["allowed_run"]["egress_decisions"][-1]["reason"] == "socks_connect_relayed"
            and report["cancelled_run"]["status"] == "cancelled"
            and report["cancelled_run"]["container_cleaned_event"]
            and all(item["own_marker"].startswith("run-") for item in concurrent_results)
            and all(not item["other_marker_exists_before_cleanup"] for item in concurrent_results)
            and not report["environment_run"]["inherited_secret_visible"]
            and report["setup_failure_run"]["reason"] == "sandbox_setup_failed"
        )
        else "fail"
    )
    output = evidence_root / "probe-report.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
