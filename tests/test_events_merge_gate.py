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

    def test_only_passing_status_values_count_as_present(self) -> None:
        failing = packet()
        failing["statuses"] = {"ci": "fail", "asdi/policy": "pass"}
        result = evaluate_merge_packet(failing, actor="merge-bot")
        self.assertEqual(result["decision"], "blocked")
        self.assertEqual(
            result["merge_dry_run"]["observed_statuses"],
            ["asdi/policy"],
        )
        self.assertIn(
            "R9-required-status-missing:ci",
            result["merge_dry_run"]["rules_fired"],
        )

    def test_stale_sha_evidence_fires_up_to_date_rule(self) -> None:
        stale = packet()
        stale["base_sha"] = "b" * 40
        stale["main_sha"] = "c" * 40
        result = evaluate_merge_packet(stale, actor="merge-bot")
        self.assertEqual(result["decision"], "blocked")
        self.assertFalse(result["merge_dry_run"]["up_to_date"])
        self.assertIn(
            "R9-branch-not-up-to-date",
            result["merge_dry_run"]["rules_fired"],
        )
        self.assertTrue(result["branch_freshness"]["evaluated"])

    def test_explicit_freshness_flag_is_honored(self) -> None:
        stale = packet()
        stale["branch_up_to_date"] = False
        result = evaluate_merge_packet(stale, actor="merge-bot")
        self.assertEqual(result["decision"], "blocked")
        self.assertFalse(result["merge_dry_run"]["up_to_date"])
        self.assertEqual(
            result["branch_freshness"]["basis"],
            "packet.branch_up_to_date",
        )

    def test_missing_freshness_evidence_is_recorded_as_not_evaluated(self) -> None:
        result = evaluate_merge_packet(packet(), actor="merge-bot")
        self.assertFalse(result["branch_freshness"]["evaluated"])
        self.assertIsNone(result["merge_dry_run"]["up_to_date"])
        self.assertIn(
            "R9-branch-freshness-not-evaluated",
            result["merge_dry_run"]["rules_fired"],
        )
        self.assertEqual(result["decision"], "human_required")
