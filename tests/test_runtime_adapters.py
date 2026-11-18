from __future__ import annotations

import unittest

from asdi.runtime import (
    ClaudeCodeAdapter,
    CodexAdapter,
    HermesAdapter,
    LocalProcessTestAdapter,
    RuntimeAdapterConfig,
    RuntimeErrorStateError,
)
from asdi.run_contract import build_run_contract


def contract() -> dict:
    return build_run_contract(
        objective="Controlled adapter lifecycle fixture",
        why="ASDI-011 requires runtime adapter contract tests.",
        constraints=[],
        out_of_scope=[],
        done_check={
            "description": "Python is available.",
            "argv": ["python3", "--version"],
        },
        human_provided=["objective", "why"],
        lead_agent_authored=["constraints", "out_of_scope", "done_check"],
    )


class RuntimeAdapterTests(unittest.TestCase):
    def test_claude_codex_and_hermes_are_separate_adapters(self) -> None:
        adapters = (ClaudeCodeAdapter(), CodexAdapter(), HermesAdapter())
        self.assertEqual(
            [adapter.name for adapter in adapters],
            ["claude_code", "codex", "hermes"],
        )
        self.assertEqual(
            [adapter.executable_names for adapter in adapters],
            [("claude",), ("codex",), ("hermes",)],
        )
        self.assertFalse(adapters[0].done_check_recheck)
        self.assertTrue(adapters[1].done_check_recheck)
        self.assertTrue(adapters[2].done_check_recheck)

    def test_explicit_command_templates_are_runtime_specific(self) -> None:
        value = contract()
        cases = [
            (
                ClaudeCodeAdapter(),
                RuntimeAdapterConfig(
                    executable_path="/opt/runtime/claude",
                    argv_prefix=(
                        "--print",
                        "--output-format",
                        "stream-json",
                    ),
                ),
            ),
            (
                CodexAdapter(),
                RuntimeAdapterConfig(
                    executable_path="/opt/runtime/codex",
                    argv_prefix=("exec", "--json"),
                ),
            ),
            (
                HermesAdapter(),
                RuntimeAdapterConfig(
                    executable_path="/opt/runtime/hermes",
                    argv_prefix=("run", "--json"),
                ),
            ),
        ]
        for adapter, config in cases:
            with self.subTest(adapter=adapter.name):
                command = adapter.build_command(
                    value, config.executable_path, config
                )
                self.assertEqual(command[0], config.executable_path)
                self.assertIn("Controlled adapter lifecycle fixture", command)
                self.assertNotIn("board", command)

    def test_missing_explicit_executable_is_detected_without_invocation(self) -> None:
        missing = "/opt/asdi-tests/missing-claude"
        for adapter in (ClaudeCodeAdapter(), CodexAdapter(), HermesAdapter()):
            with self.subTest(adapter=adapter.name):
                self.assertIsNone(
                    adapter.resolve_executable(
                        RuntimeAdapterConfig(executable_path=missing)
                    )
                )

    def test_actual_adapters_are_not_marked_synthetic(self) -> None:
        for adapter in (ClaudeCodeAdapter(), CodexAdapter(), HermesAdapter()):
            with self.subTest(adapter=adapter.name):
                self.assertFalse(adapter.development_safe)

    def test_nested_orchestration_is_rejected(self) -> None:
        adapter = LocalProcessTestAdapter()
        with self.assertRaises(RuntimeErrorStateError):
            adapter.validate_runtime_command(("/usr/bin/archon", "dispatch"))

    def test_synthetic_adapter_has_a_small_utility_allowlist(self) -> None:
        adapter = LocalProcessTestAdapter()
        self.assertEqual(
            adapter.allowed_utilities,
            {"echo", "false", "pwd", "sleep", "true"},
        )
        with self.assertRaises(RuntimeErrorStateError):
            adapter.validate_runtime_command(("/bin/sh", "-c", "echo unsafe"))


if __name__ == "__main__":
    unittest.main()
