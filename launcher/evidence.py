#!/usr/bin/env python3
"""Write-once, content-addressed evidence store (REV K Pass 1)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


class EvidenceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def put(
        self,
        source_dir: str | Path,
        result: dict[str, Any],
        *,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        source = Path(source_dir).resolve()
        result_path = source / "result.json"
        if not result_path.is_file():
            raise ValueError("evidence directory must contain result.json")
        observed = json.loads(result_path.read_text())
        required = {"schema", "run_id", "commit", "features"}
        if set(observed) != required:
            raise ValueError("result.json fields do not match schema 2")
        if not observed.get("run_id") or not observed.get("commit"):
            raise ValueError("evidence must be bound to a run and revision")
        for feature in observed.get("features", []):
            if "limits" not in feature:
                raise ValueError("every feature check must state limits")
        if result is not None and observed != result:
            raise ValueError("result does not match caller-provided result")

        metadata_required = {"source", "producer", "environment", "inputs"}
        if set(metadata) != metadata_required:
            raise ValueError(
                "evidence metadata must contain source, producer, environment and inputs"
            )
        if not isinstance(metadata["producer"], dict) or metadata["producer"].get("kind") != "verifier":
            raise ValueError("evidence producer must identify the verifier")
        if not isinstance(metadata["environment"], dict) or not metadata["environment"].get(
            "run_image_digest"
        ):
            raise ValueError("evidence environment must contain the run image digest")
        inputs = metadata.get("inputs")
        required_inputs = {"harness_commit", "static_gates", "product_profile"}
        if not isinstance(inputs, dict) or set(inputs) != required_inputs:
            raise ValueError("evidence inputs must bind harness, gates and product profile")

        statement_identity = {
            "subject": [{"name": "asdi-run", "digest": {"gitCommit": observed["commit"]}}],
            "predicateType": "https://asdi.local/verification/v1",
            "predicate": {
                "source": metadata["source"],
                "run_id": observed["run_id"],
                "producer": metadata["producer"],
                "environment": metadata["environment"],
                "inputs": metadata["inputs"],
                "checks": [
                    {
                        "id": f"feature:{item['id']}",
                        "status": item["status"],
                        "control": item["control"],
                        "limits": item["limits"],
                    }
                    for item in observed["features"]
                ],
            },
        }
        manifest_id = "m-" + hashlib.sha256(
            json.dumps(statement_identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        manifest_root = self.root / manifest_id
        if manifest_root.exists():
            return self.verify(manifest_id)
        manifest_root.mkdir(parents=True)
        file_records: list[dict[str, Any]] = []
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.name == "result.json":
                continue
            relative = path.relative_to(source)
            destination = manifest_root / "objects" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            os.chmod(destination, 0o444)
            file_records.append(
                {
                    "path": str(relative),
                    "sha256": self._sha256(destination),
                    "bytes": path.stat().st_size,
                    "kind": "log",
                }
            )
        statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": "asdi-run", "digest": {"gitCommit": observed["commit"]}}],
            "predicateType": "https://asdi.local/verification/v1",
            "predicate": {
                "manifest_id": manifest_id,
                "source": metadata["source"],
                "run_id": observed["run_id"],
                "producer": metadata["producer"],
                "environment": metadata["environment"],
                "inputs": metadata["inputs"],
                "checks": statement_identity["predicate"]["checks"],
                "files": file_records,
            },
        }
        _atomic_json(manifest_root / "result.json", observed)
        _atomic_json(manifest_root / "statement.json", statement)
        os.chmod(manifest_root / "result.json", 0o444)
        os.chmod(manifest_root / "statement.json", 0o444)
        return self.verify(manifest_id)

    def verify(self, manifest_id: str) -> dict[str, Any]:
        root = self.root / manifest_id
        statement_path = root / "statement.json"
        result_path = root / "result.json"
        if not statement_path.is_file() or not result_path.is_file():
            raise ValueError("manifest not found")
        statement = json.loads(statement_path.read_text())
        result = json.loads(result_path.read_text())
        failures: list[str] = []
        if statement["predicate"]["run_id"] != result["run_id"]:
            failures.append("run_id mismatch")
        for item in statement["predicate"].get("files", []):
            path = root / "objects" / item["path"]
            if not path.is_file():
                failures.append(f"missing {item['path']}")
            elif _sha256(path) != item["sha256"]:
                failures.append(f"hash mismatch {item['path']}")
        if failures:
            raise ValueError("invalid evidence: " + "; ".join(failures))
        if not statement["predicate"].get("producer", {}).get("image_digest"):
            failures.append("missing producer image digest")
        if not statement["predicate"].get("environment", {}).get("run_image_digest"):
            failures.append("missing run image digest")
        inputs = statement["predicate"].get("inputs", {})
        if set(inputs) != {"harness_commit", "static_gates", "product_profile"}:
            failures.append("incomplete evidence input binding")
        if failures:
            raise ValueError("invalid evidence: " + "; ".join(failures))
        return {"manifest_id": manifest_id, "valid": True, "statement": statement, "result": result}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)
