#!/usr/bin/env python3
"""Minimal JSON Schema checker for the subset used by ASDI REV K."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


class ValidationError(ValueError):
    pass


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    if "$ref" not in schema:
        return schema
    ref = schema["$ref"]
    if not ref.startswith("#/"):
        raise ValidationError(f"unsupported $ref: {ref}")
    target: Any = root
    for part in ref[2:].split("/"):
        target = target[part.replace("~1", "/").replace("~0", "~")]
    if isinstance(target, dict) and "$ref" in target:
        return _resolve(target, root)
    return target


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str) -> None:
    schema = _resolve(schema, root)
    if "const" in schema and value != schema["const"]:
        raise ValidationError(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(f"{path}: must be one of {schema['enum']!r}")

    expected = schema.get("type")
    if expected:
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
        if not any(checks[item](value) for item in allowed):
            raise ValidationError(f"{path}: expected type {expected!r}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValidationError(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise ValidationError(f"{path}: unknown properties {sorted(unknown)!r}")
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], root, f"{path}/{key}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ValidationError(f"{path}: fewer than {schema['minItems']} items")
        if schema.get("uniqueItems") and len(value) != len({json.dumps(item, sort_keys=True) for item in value}):
            raise ValidationError(f"{path}: items are not unique")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate(item, item_schema, root, f"{path}/{index}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ValidationError(f"{path}: string is too short")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValidationError(f"{path}: does not match {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValidationError(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValidationError(f"{path}: above maximum {schema['maximum']}")


def validate_file(schema_path: str | Path, instance_path: str | Path) -> int:
    parser = argparse.ArgumentParser()
    schema = json.loads(Path(schema_path).read_text())
    value = json.loads(Path(instance_path).read_text())
    try:
        _validate(value, schema, schema, "$")
    except ValidationError as error:
        print(f"INVALID: {error}", file=__import__("sys").stderr)
        return 1
    print(f"VALID: {instance_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", required=True)
    parser.add_argument("--instance", required=True)
    arguments = parser.parse_args()
    return validate_file(arguments.schema, arguments.instance)


if __name__ == "__main__":
    raise SystemExit(main())
