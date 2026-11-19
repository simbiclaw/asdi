from __future__ import annotations

import unittest

from events.merge_gate import evaluate_merge_packet


HEAD = "a" * 40


def packet(*, policy_decision: str = "eligible", change_class: str = "agent_mergeable") -> dict:
    return {
        "schema_version": "asdi.pr-packet/v1",
        "pr_number": 7,
        "head_sha": HEAD,
        "policy_decision": policy_decision,
        "statuses": {"ci": "pass", "asdi/policy": "pass"},
        "classification": {"change_class": change_class},
    }


class MergeGateTests(unittest.TestCase):
    def test_t0_merge_bot_requires_human_and_executes_nothing(self) -> None:
        result = evaluate_merge_packet(packet(), actor="merge-bot")
        self.assertEqual(result["decision"], "human_required")
        self.assertTrue(result["human_required"])
        self.assertFalse(result["merge_executed"])
        self.assertIn("governance requires a human merge", result["reason"])

    def test_agent_identity_is_refused(self) -> None:
        result = evaluate_merge_packet(packet(), actor="agents")
        self.assertEqual(result["decision"], "refused")
        self.assertFalse(result["merge_executed"])
        self.assertIn("agent or status identity cannot merge", result["reason"])

    def test_noneligible_gate_blocks_merge_dry_run(self) -> None:
        result = evaluate_merge_packet(
            packet(policy_decision="human_required"),
            actor="merge-bot",
        )
        self.assertEqual(result["decision"], "blocked")
        self.assertIsNone(result["merge_dry_run"])
        self.assertFalse(result["human_required"])

    def test_judgment_change_remains_human_governed(self) -> None:
        result = evaluate_merge_packet(
            packet(change_class="judgment"),
            actor="merge-bot",
        )
        self.assertEqual(result["decision"], "human_required")
        self.assertTrue(result["human_required"])
