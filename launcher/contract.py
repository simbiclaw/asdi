#!/usr/bin/env python3
"""REV K run-contract validation using the Phase 0 schema subset."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "run-contract.schema.json"


class ContractError(ValueError):
    pass


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    if "$ref" not in schema:
        return schema
    target: Any = root
    for part in schema["$ref"][2:].split("/"):
        target = target[part.replace("~1", "/").replace("~0", "~")]
    return _resolve(target, root) if isinstance(target, dict) else target


ROOT_SCHEMA = json.loads(SCHEMA.read_text())


def validate(value: Any, schema: dict[str, Any] | None = None, *, path: str = "$") -> dict[str, Any]:
    root = ROOT_SCHEMA
    schema = _resolve(schema or root, root)
    root = json.loads(SCHEMA.read_text())
    schema = _resolve(schema, root)
    if "const" in schema and value != schema["const"]:
        raise ContractError(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: must be one of {schema['enum']!r}")
    expected = schema.get("type")
    checks = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "null": lambda v: v is None,
    }
    allowed = expected if isinstance(expected, list) else [expected]
    if expected and not any(checks[item](value) for item in allowed):
        raise ContractError(f"{path}: expected type {expected!r}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ContractError(f"{path}: missing {key!r}")
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(schema.get("properties", {}))
            if unknown:
                raise ContractError(f"{path}: unknown {sorted(unknown)!r}")
        for key, item in value.items():
            child = schema.get("properties", {}).get(key)
            if child:
                validate(item, child, path=f"{path}/{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ContractError(f"{path}: too few items")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise ContractError(f"{path}: duplicate items")
        item_schema = schema.get("items")
        for index, item in enumerate(value):
            if item_schema:
                validate(item, item_schema, path=f"{path}/{index}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ContractError(f"{path}: too short")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ContractError(f"{path}: pattern mismatch")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", value):
            raise ContractError(f"{path}: below minimum")
    return value


def load_contract(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    text = source.read_text()
    value = (
        yaml.safe_load(text)
        if source.suffix.lower() in {".yaml", ".yml"}
        else json.loads(text)
    )
    return validate(value)
