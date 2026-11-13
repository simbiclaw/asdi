from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from asdi.runtime import (
    ADAPTERS,
    ClaudeCodeAdapter,
    CodexAdapter,
    HermesAdapter,
    LocalProcessTestAdapter,
    RunLauncher,
    RunStore,
    RuntimeAdapterConfig,
    RuntimeErrorStateError,
    process_alive,
)
from asdi.run_contract import (
    RunContractValidationError,
    build_run_contract,
)


def synthetic_contract() -> dict:
    return build_run_contract(
        objective="Controlled local process lifecycle fixture",
        why="ASDI-011 requires actual process cancellation and durable evidence.",
        constraints=["Synthetic process only"],
        out_of_scope=["Agent execution", "Network access", "Container execution"],
        done_check={
            "description": "Python runtime is available.",
            "argv": ["python3", "--version"],
        },
        human_provided=["objective", "why"],
        lead_agent_authored=["constraints", "out_of_scope", "done_check"],
    )


class RunLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.store = RunStore(self.root)
        self.launcher = RunLauncher(self.store)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def local_adapter(self, utility: str, *arguments: str) -> RuntimeAdapterConfig:
        executable = shutil.which(utility)
        assert executable is not None
        return RuntimeAdapterConfig(
            executable_path=executable,
            argv_suffix=tuple(arguments),
            include_objective=False,
        )

    def start_local(
        self,
        utility: str,
        *arguments: str,
        run_id: str | None = None,
    ):
        if run_id is None:
            created = self.launcher.create_run(synthetic_contract())
            run_id = created["run_id"]
        return self.launcher.start_runtime(
            run_id,
            LocalProcessTestAdapter.name,
            self.local_adapter(utility, *arguments),
            isolation_mode="host_process_test",
            allow_noncompliant_test=True,
        )

    def test_invalid_contract_cannot_create_a_run(self) -> None:
        contract = synthetic_contract()
        contract["guardrails"]["max_spend_usd"] = "unlimited"
        before = set((self.root / "runs").glob("*")) if (self.root / "runs").exists() else set()
        with self.assertRaises(RunContractValidationError):
            self.launcher.create_run(contract)
        after = set((self.root / "runs").glob("*")) if (self.root / "runs").exists() else set()
        self.assertEqual(before, after)

    def test_missing_runtime_is_a_durable_failure(self) -> None:
        created = self.launcher.create_run(synthetic_contract())
        run_id = created["run_id"]
        with self.assertRaises(RuntimeErrorStateError):
            self.launcher.start_runtime(
                run_id,
                ClaudeCodeAdapter.name,
                RuntimeAdapterConfig(
                    executable_path="/opt/asdi-tests/missing-claude",
                    argv_prefix=("--print",),
                ),
                isolation_mode="container",
            )
        persisted = self.store.load_run(run_id)
        self.assertEqual(persisted["status"], "failed")
        self.assertEqual(persisted["result"]["reason"], "missing_runtime")
        self.assertEqual(
            [event["type"] for event in self.store.events(run_id)][-1],
            "run_failed",
        )

    def test_actual_runtime_fails_closed_without_container_boundary(self) -> None:
        created = self.launcher.create_run(synthetic_contract())
        run_id = created["run_id"]
        with self.assertRaises(RuntimeErrorStateError):
            self.launcher.start_runtime(
                run_id,
                ClaudeCodeAdapter.name,
                RuntimeAdapterConfig(
                    executable_path="/usr/bin/true",
                    argv_prefix=("--print",),
                ),
                isolation_mode="container",
            )
        state = self.store.load_run(run_id)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["result"]["reason"], "sandbox_not_configured")
        self.assertFalse(state["isolation_compliant"])

    def test_actual_process_cancellation_persists_terminal_evidence(self) -> None:
        created = self.launcher.create_run(
            synthetic_contract(),
            board_task_reference="local-cancellation-test",
        )
        run_id = created["run_id"]
        handle = self.start_local("sleep", "30", run_id=run_id)
        state = self.store.load_run(run_id)
        self.assertEqual(state["status"], "running")
        self.assertTrue(process_alive(state["process"]["pid"]))

        final = handle.cancel(timeout=2)
        self.assertEqual(final["status"], "cancelled")
        self.assertTrue(final["cancel_requested"])
        self.assertEqual(final["result"]["signal"], "SIGTERM")
        self.assertIsNotNone(final["result"]["exit_code"])
        self.assertFalse(process_alive(final["process"]["pid"]))

        reloaded = RunStore(self.root).load_run(run_id)
        self.assertEqual(reloaded["status"], "cancelled")
        events = self.store.events(run_id)
        self.assertIn("runtime_started", {event["type"] for event in events})
        self.assertIn("cancel_requested", {event["type"] for event in events})
        self.assertIn("process_cancelled", {event["type"] for event in events})
        sequences = [event["sequence"] for event in events]
        self.assertEqual(sequences, list(range(1, len(sequences) + 1)))

    def test_successful_runtime_requires_launcher_done_check(self) -> None:
        handle = self.start_local("true")
        state = handle.wait(timeout=5)
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["result"]["done_check_source"], "launcher_recheck")
        self.assertEqual(state["done_check"]["exit_code"], 0)

    def test_runtime_failure_is_durable_and_skips_done_check(self) -> None:
        handle = self.start_local("false")
        state = handle.wait(timeout=5)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["result"]["reason"], "runtime_failure")
        self.assertEqual(state["result"]["exit_code"], 1)
        self.assertIsNone(state["done_check"])

    def test_structured_runtime_output_and_usage_are_persisted(self) -> None:
        handle = self.start_local(
            "echo",
            '{"type":"result","usage":{"usd_cost":1.25,"turns":3}}',
        )
        state = handle.wait(timeout=5)
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["usage"]["usd_cost"], 1.25)
        self.assertEqual(state["usage"]["turns"], 3)
        runtime_output_payloads = [
            event["payload"]
            for event in self.store.events(state["run_id"])
            if event["type"] == "runtime_output"
        ]
        structured = [
            payload["structured"]
            for payload in runtime_output_payloads
            if "structured" in payload
        ]
        self.assertTrue(structured)
        self.assertIn("usage_observed", {event["type"] for event in self.store.events(state["run_id"])})

    def test_host_restart_after_process_exit_is_durable_failure(self) -> None:
        handle = self.start_local("sleep", "0.2")
        run_id = handle.run_id
        time.sleep(0.5)
        # Reap the known test child, as the original launcher parent would.
        self.assertIsNotNone(handle.process.poll())
        recovered = RunLauncher(RunStore(self.root)).recover_run(run_id)
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["result"]["reason"], "host_restart_orphaned")
        self.assertEqual(recovered["result"]["pid"], handle.pid)

    def test_missing_process_identity_is_a_recovery_failure(self) -> None:
        created = self.launcher.create_run(synthetic_contract())
        run_id = created["run_id"]
        self.store.transition(
            run_id,
            {
                "status": "running",
                "process": {
                    "pid": None,
                    "process_group": None,
                    "process_start_time": None,
                },
                "runtime": {"adapter": LocalProcessTestAdapter.name},
            },
            expected_statuses={"created"},
        )
        recovered = self.launcher.recover_run(run_id)
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["result"]["reason"], "missing_process_identity")

    def test_each_actual_adapter_exercises_common_lifecycle_with_synthetic_process(self) -> None:
        sleep = shutil.which("sleep")
        self.assertIsNotNone(sleep)
        for adapter_class in (ClaudeCodeAdapter, CodexAdapter, HermesAdapter):
            with self.subTest(adapter=adapter_class.__name__):
                created = self.launcher.create_run(synthetic_contract())
                run_id = created["run_id"]
                adapter = adapter_class()
                # Test-only override: launch a harmless sleep through each
                # adapter object. This does not execute the vendor CLI.
                original_safety = adapter_class.development_safe
                adapter_class.development_safe = True
                try:
                    handle = self.launcher.start_runtime(
                        run_id,
                        adapter.name,
                        RuntimeAdapterConfig(
                            executable_path=sleep,
                            argv_suffix=("30",),
                            include_objective=False,
                        ),
                        isolation_mode="host_process_test",
                        allow_noncompliant_test=True,
                    )
                    self.assertTrue(handle.is_running())
                    final = handle.cancel(timeout=2)
                    self.assertEqual(final["status"], "cancelled")
                    self.assertEqual(final["runtime"]["adapter"], adapter.name)
                    self.assertEqual(final["result"]["signal"], "SIGTERM")
                finally:
                    adapter_class.development_safe = original_safety

    def test_installed_runtime_executables_resolve_without_invocation(self) -> None:
        candidates = {
            ClaudeCodeAdapter: "claude",
            CodexAdapter: "codex",
            HermesAdapter: "hermes",
        }
        for adapter_class, binary in candidates.items():
            with self.subTest(adapter=adapter_class.__name__, binary=binary):
                installed = shutil.which(binary)
                if installed is None:
                    self.skipTest(f"{binary} is not installed")
                adapter = adapter_class()
                resolved = adapter.resolve_executable(
                    RuntimeAdapterConfig(executable_path=installed)
                )
                self.assertEqual(resolved, installed)

    def test_adapter_registry_is_explicit_and_board_neutral(self) -> None:
        self.assertEqual(
            set(ADAPTERS),
            {
                "claude_code",
                "codex",
                "hermes",
                "local_process_test",
            },
        )
        self.assertNotIn("multica", ADAPTERS)
        self.assertNotIn("paperclip", ADAPTERS)


if __name__ == "__main__":
    unittest.main()
