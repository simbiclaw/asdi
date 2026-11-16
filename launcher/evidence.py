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

    def put(self, source_dir: str | Path, result: dict[str, Any]) -> dict[str, Any]:
        source = Path(source_dir).resolve()
        result_path = source / "result.json"
        if not result_path.is_file():
            raise ValueError("evidence directory must contain result.json")
        observed = json.loads(result_path.read_text())
        required = {"schema", "run_id", "commit", "features"}
        if set(observed) != required:
            raise ValueError("result.json fields do not match schema 2")
        for feature in observed.get("features", []):
            if "limits" not in feature:
                raise ValueError("every feature check must state limits")
        if result is not None and observed != result:
            raise ValueError("result does not match caller-provided result")

        manifest_id = "m-" + hashlib.sha256(observed["commit"].encode()).hexdigest()[:24]
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
                "source": "run",
                "run_id": observed["run_id"],
                "checks": [
                    {
                        "id": f"feature:{item['id']}",
                        "status": item["status"],
                        "control": item["control"],
                        "limits": item["limits"],
                    }
                    for item in observed["features"]
                ],
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
        return {"manifest_id": manifest_id, "valid": True, "statement": statement, "result": result}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
