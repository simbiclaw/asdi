#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from events.verification import main_verification_event_payload, verification_event_payload
from launcher.evidence import EvidenceStore


HEAD = "a" * 40


def verified_evidence(
    root: Path,
    *,
    control: str = "caught",
    source: str = "pr-head",
) -> dict:
    evidence_directory = root / "source"
    evidence_directory.mkdir()
    result = {
        "schema": 2,
        "run_id": "r-verification",
        "commit": HEAD,
        "features": [
            {
                "id": "feature:test",
                "status": "pass",
                "control": control,
                "evidence": ["output.txt"],
                "limits": [],
            }
        ],
    }
    (evidence_directory / "result.json").write_text(json.dumps(result))
    (evidence_directory / "output.txt").write_text("observed\n")
    store = EvidenceStore(root / "store")
    return store.put(
        evidence_directory,
        result,
        metadata={
            "source": source,
            "producer": {"kind": "verifier", "image_digest": "sha256:verifier"},
            "environment": {
                "run_image_digest": "sha256:run",
                "tool_versions": {"python": "3"},
            },
            "inputs": {
                "harness_commit": "b" * 40,
                "static_gates": "c" * 64,
                "product_profile": "d" * 64,
            },
        },
    )


class VerificationEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.packet = {"pr_number": 7, "head_sha": HEAD}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_verified_pr_head_evidence_maps_to_gate_payload(self) -> None:
        payload = verification_event_payload(
            packet=self.packet,
            evidence=verified_evidence(self.root),
            ci_status="pass",
        )
        self.assertEqual(payload["statuses"], {"ci": "pass"})
        self.assertEqual(payload["verifier"]["candidate_commit"], HEAD)
        self.assertEqual(payload["verifier"]["status"], "pass")
        self.assertTrue(payload["verifier"]["manifest_id"].startswith("m-"))

    def test_verified_main_evidence_maps_to_post_merge_payload(self) -> None:
        payload = main_verification_event_payload(
            commit=HEAD,
            evidence=verified_evidence(self.root, source="main"),
            ci_status="pass",
        )
        self.assertEqual(payload["commit"], HEAD)
        self.assertEqual(payload["statuses"], {"ci": "pass"})
        self.assertEqual(payload["verifier"]["status"], "pass")

    def test_main_workflow_rejects_pr_head_source(self) -> None:
        with self.assertRaises(ValueError):
            main_verification_event_payload(
                commit=HEAD,
                evidence=verified_evidence(self.root, source="pr-head"),
                ci_status="pass",
            )

    def test_missed_negative_control_is_fail_not_pass(self) -> None:
        payload = verification_event_payload(
            packet=self.packet,
            evidence=verified_evidence(self.root, control="missed"),
            ci_status="pass",
        )
        self.assertEqual(payload["verifier"]["status"], "fail")
        self.assertIn(
            "feature feature:test control was not caught",
            payload["verifier"]["failures"],
        )

    def test_stale_or_wrong_source_evidence_is_rejected(self) -> None:
        evidence = verified_evidence(self.root)
        evidence["statement"]["predicate"]["source"] = "main"
        with self.assertRaises(ValueError):
            verification_event_payload(
                packet=self.packet,
                evidence=evidence,
                ci_status="pass",
            )
