#!/usr/bin/env python3
"""Write-once, content-addressed evidence store (REV K Pass 1)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


RUN_ID = re.compile(r"^r-[A-Za-z0-9-]+$")


class EvidenceStore:
    ALLOWED_FILE_KINDS = {
        "log",
        "value",
        "diff",
        "http",
        "screenshot",
        "video",
        "trace",
        "heap",
    }
    ALLOWED_RESULT_STATUSES = {
        "pass",
        "fail",
        "blocked",
        "error",
        "not_applicable",
    }
    ALLOWED_CONTROL_STATUSES = {"caught", "missed", "not_applicable"}
    ALLOWED_SOURCES = {
        "run",
        "pr-head",
        "main",
        "drift",
        "prod-probe",
        "canary",
        "seed",
    }

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
        if result is not None and observed != result:
            raise ValueError("result does not match caller-provided result")

        metadata_required = {"source", "producer", "environment", "inputs"}
        if set(metadata) != metadata_required:
            raise ValueError(
                "evidence metadata must contain source, producer, environment and inputs"
            )
        if not isinstance(metadata["producer"], dict) or metadata["producer"].get("kind") != "verifier":
            raise ValueError("evidence producer must identify the verifier")
        if not metadata["producer"].get("image_digest"):
            raise ValueError("evidence producer must identify its image")
        if not isinstance(metadata["environment"], dict) or not metadata["environment"].get(
            "run_image_digest"
        ):
            raise ValueError("evidence environment must contain the run image digest")
        if not isinstance(metadata["environment"].get("tool_versions"), dict):
            raise ValueError("evidence environment must contain tool versions")
        inputs = metadata.get("inputs")
        required_inputs = {"harness_commit", "static_gates", "product_profile"}
        if not isinstance(inputs, dict) or set(inputs) != required_inputs:
            raise ValueError("evidence inputs must bind harness, gates and product profile")
        if not isinstance(inputs["harness_commit"], str) or not inputs["harness_commit"]:
            raise ValueError("evidence input bindings must contain the harness revision")
        if any(
            not isinstance(inputs[name], str) or len(inputs[name]) != 64
            for name in ("static_gates", "product_profile")
        ):
            raise ValueError("gate and profile input bindings must contain SHA-256 values")
        if metadata["source"] not in self.ALLOWED_SOURCES:
            raise ValueError("evidence source is not allowed")

        self._validate_result(observed, file_paths=None)
        static_checks = self._read_static_checks(source, observed["run_id"])
        self._validate_static_checks(static_checks, observed["run_id"])

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
                "static_checks": static_checks,
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
        self._validate_result(observed, file_paths={item["path"] for item in file_records})
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
                "static_checks": static_checks,
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
        try:
            file_records = statement["predicate"].get("files", [])
            recorded_paths = {item["path"] for item in file_records}
            self._validate_result(result, file_paths=recorded_paths)
        except (KeyError, TypeError, ValueError) as error:
            failures.append(str(error))
        if statement["predicate"]["run_id"] != result["run_id"]:
            failures.append("run_id mismatch")
        if statement.get("_type") != "https://in-toto.io/Statement/v1":
            failures.append("statement type mismatch")
        if statement.get("predicateType") != "https://asdi.local/verification/v1":
            failures.append("statement predicate type mismatch")
        subject = statement.get("subject", [])
        if (
            len(subject) != 1
            or subject[0].get("digest", {}).get("gitCommit") != result.get("commit")
        ):
            failures.append("subject revision mismatch")
        predicate = statement.get("predicate", {})
        expected_checks = [
            {
                "id": f"feature:{item['id']}",
                "status": item["status"],
                "control": item["control"],
                "limits": item["limits"],
            }
            for item in result.get("features", [])
        ]
        if predicate.get("checks") != expected_checks:
            failures.append("statement checks do not match result")
        static_checks = predicate.get("static_checks")
        if static_checks is None:
            failures.append("statement is missing static_checks")
        else:
            try:
                self._validate_static_checks(static_checks, result.get("run_id"))
            except (TypeError, ValueError) as error:
                failures.append(str(error))
        for item in statement["predicate"].get("files", []):
            recorded_path = item.get("path")
            path = root / "objects" / recorded_path if isinstance(recorded_path, str) else None
            if (
                not isinstance(recorded_path, str)
                or not recorded_path
                or Path(recorded_path).is_absolute()
                or ".." in Path(recorded_path).parts
                or path is None
            ):
                failures.append("unsafe evidence path")
            elif not path.is_file():
                failures.append(f"missing {recorded_path}")
            elif _sha256(path) != item.get("sha256"):
                failures.append(f"hash mismatch {recorded_path}")
            if item.get("kind") not in self.ALLOWED_FILE_KINDS:
                failures.append(f"invalid evidence kind for {recorded_path}")
            if not isinstance(item.get("bytes"), int) or item.get("bytes") < 0:
                failures.append(f"invalid evidence size for {recorded_path}")
            elif path is not None and path.is_file() and item["bytes"] != path.stat().st_size:
                failures.append(f"size mismatch {recorded_path}")
        actual_objects = {
            str(path.relative_to(root / "objects"))
            for path in (root / "objects").rglob("*")
            if path.is_file()
        } if (root / "objects").is_dir() else set()
        try:
            expected_objects = {item["path"] for item in statement["predicate"].get("files", [])}
        except (KeyError, TypeError):
            expected_objects = set()
        if actual_objects != expected_objects:
            failures.append("stored objects do not match statement")
        if failures:
            raise ValueError("invalid evidence: " + "; ".join(failures))
        if not statement["predicate"].get("producer", {}).get("image_digest"):
            failures.append("missing producer image digest")
        if not statement["predicate"].get("environment", {}).get("run_image_digest"):
            failures.append("missing run image digest")
        if not isinstance(
            statement["predicate"].get("environment", {}).get("tool_versions"), dict
        ):
            failures.append("missing tool versions")
        inputs = statement["predicate"].get("inputs", {})
        if set(inputs) != {"harness_commit", "static_gates", "product_profile"}:
            failures.append("incomplete evidence input binding")
        if statement["predicate"].get("source") not in self.ALLOWED_SOURCES:
            failures.append("invalid evidence source")
        if failures:
            raise ValueError("invalid evidence: " + "; ".join(failures))
        return {"manifest_id": manifest_id, "valid": True, "statement": statement, "result": result}

    def _validate_result(self, result: Any, *, file_paths: set[str] | None) -> None:
        if not isinstance(result, dict) or set(result) != {"schema", "run_id", "commit", "features"}:
            raise ValueError("result.json fields do not match schema 2")
        if (
            result.get("schema") != 2
            or not isinstance(result.get("run_id"), str)
            or not RUN_ID.fullmatch(result["run_id"])
            or not result.get("commit")
        ):
            raise ValueError("result.json is not bound to schema, run and revision")
        features = result.get("features")
        if not isinstance(features, list) or not features:
            raise ValueError("result.json features must be a non-empty array")
        for feature in features:
            if not isinstance(feature, dict):
                raise ValueError("feature result must be an object")
            required_feature = {"id", "status", "control", "evidence", "limits"}
            if set(feature) != required_feature:
                raise ValueError("feature result fields do not match schema 2")
            if feature.get("status") not in self.ALLOWED_RESULT_STATUSES:
                raise ValueError("feature result has an invalid status")
            if feature.get("control") not in self.ALLOWED_CONTROL_STATUSES:
                raise ValueError("feature result has an invalid control value")
            evidence_paths = feature.get("evidence")
            if not isinstance(evidence_paths, list) or any(
                not isinstance(path, str) for path in evidence_paths
            ):
                raise ValueError("feature evidence must be an array of paths")
            if file_paths is not None and not set(evidence_paths).issubset(file_paths):
                raise ValueError("feature evidence references an unrecorded file")
            if not isinstance(feature.get("limits"), list) or any(
                not isinstance(limit, str) for limit in feature.get("limits")
            ):
                raise ValueError("feature limits must be an array of strings")

    @staticmethod
    def _read_static_checks(source: Path, run_id: str) -> Any:
        path = source / ".asdi-evidence" / "static-gates.json"
        if not path.is_file():
            raise ValueError("static gate checks are required in .asdi-evidence/static-gates.json")
        try:
            value = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid static gate checks: {error}") from error
        return value

    @staticmethod
    def _validate_static_checks(value: Any, run_id: str) -> None:
        if not isinstance(value, dict) or set(value) != {"run_id", "checks"}:
            raise ValueError("static_checks must contain run_id and checks")
        if value.get("run_id") != run_id:
            raise ValueError("static_checks run_id mismatch")
        checks = value.get("checks")
        if not isinstance(checks, list) or not checks:
            raise ValueError("static_checks checks must be a non-empty array")
        seen: set[str] = set()
        has_static_gate = False
        for check in checks:
            if not isinstance(check, dict):
                raise ValueError("static check must be an object")
            check_id = check.get("id")
            if not isinstance(check_id, str) or not check_id:
                raise ValueError("gate check id is required")
            if check_id in seen:
                raise ValueError("gate check id is duplicated")
            seen.add(check_id)
            if check.get("status") not in {"pass", "fail", "error", "blocked"}:
                raise ValueError("gate check status is invalid")
            if "blocking" in check and type(check["blocking"]) is not bool:
                raise ValueError("gate check blocking must be boolean")
            has_static_gate = has_static_gate or check_id.startswith("static:")
        if not has_static_gate:
            raise ValueError("static_checks must include a named static gate")


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
