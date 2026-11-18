from __future__ import annotations

import json
import os
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from launcher.contract import ContractError, load_contract
from launcher.evidence import EvidenceStore


ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_valid_contract_loads(self) -> None:
        value = load_contract(ROOT / "schemas/examples/run-contract.valid.json")
        self.assertEqual(value["task_type"], "feature.cli")

    def test_missing_done_check_fails_closed(self) -> None:
        value = json.loads((ROOT / "schemas/examples/run-contract.valid.json").read_text())
        del value["done_check"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(value))
            with self.assertRaises(ContractError):
                load_contract(path)


class EvidenceStoreTests(unittest.TestCase):
    def test_evidence_is_content_addressed_and_survives_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "evidence"
            source.mkdir()
            (source / "result.json").write_text(
                json.dumps(
                    {
                        "schema": 2,
                        "run_id": "r-test",
                        "commit": "abc123",
                        "features": [
                            {
                                "id": "feature:test",
                                "status": "pass",
                                "control": "caught",
                                "evidence": ["output.txt"],
                                "limits": ["UI not tested"],
                            }
                        ],
                    }
                )
            )
            (source / "output.txt").write_text("observed\n")
            store = EvidenceStore(Path(temporary) / "store")
            metadata = {
                "source": "run",
                "producer": {"kind": "verifier", "image_digest": "sha256:verifier"},
                "environment": {
                    "run_image_digest": "sha256:run",
                    "tool_versions": {"python": "3"},
                },
                "inputs": {
                    "harness_commit": "base123",
                    "static_gates": "a" * 64,
                    "product_profile": "b" * 64,
                },
            }
            first = store.put(
                source,
                json.loads((source / "result.json").read_text()),
                metadata=metadata,
            )
            self.assertTrue(first["valid"])
            again = store.verify(first["manifest_id"])
            self.assertEqual(again["result"]["features"][0]["status"], "pass")
            object_path = (
                Path(temporary)
                / "store"
                / first["manifest_id"]
                / "objects"
                / "output.txt"
            )
            os.chmod(object_path, 0o644)
            object_path.write_text("tampered\n")
            with self.assertRaises(ValueError):
                store.verify(first["manifest_id"])

    def test_evidence_manifest_is_unique_per_run_with_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "evidence"
            source.mkdir()
            result = {
                "schema": 2,
                "run_id": "r-test",
                "commit": "abc123",
                "features": [
                    {
                        "id": "feature:test",
                        "status": "pass",
                        "control": "caught",
                        "evidence": [],
                        "limits": ["fixture"],
                    }
                ],
            }
            (source / "result.json").write_text(json.dumps(result))
            metadata = {
                "source": "run",
                "producer": {"kind": "verifier", "image_digest": "sha256:verifier"},
                "environment": {
                    "run_image_digest": "sha256:run",
                    "tool_versions": {"python": "3"},
                },
                "inputs": {
                    "harness_commit": "base123",
                    "static_gates": "a" * 64,
                    "product_profile": "b" * 64,
                },
            }
            store = EvidenceStore(Path(temporary) / "store")
            first = store.put(source, result, metadata=metadata)
            result["run_id"] = "r-other"
            (source / "result.json").write_text(json.dumps(result))
            second = store.put(source, result, metadata=metadata)
            self.assertNotEqual(first["manifest_id"], second["manifest_id"])
            self.assertEqual(
                second["statement"]["predicate"]["producer"],
                metadata["producer"],
            )
