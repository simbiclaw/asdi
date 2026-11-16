#!/usr/bin/env python3
"""Validate every REV K schema example, including YAML/front-matter forms."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from tools.validate_schema import validate_file as validate


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def yaml_to_json(path: Path) -> str:
    completed = subprocess.run(
        ["ruby", "-e", 'require "yaml"; require "json"; print JSON.generate(YAML.safe_load(ARGF.read))', path],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def front_matter_to_json(path: Path) -> str:
    text = path.read_text()
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"no front matter in {path}")
    temporary = ROOT / ".asdi-fixture-frontmatter.yaml"
    temporary.write_text(match.group(1))
    try:
        return yaml_to_json(temporary)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    cases = [
        ("run-contract.schema.json", "run-contract.valid.json", "json"),
        ("product.schema.json", "product.valid.json", "json"),
        ("verify.schema.json", "verify.valid.yaml", "yaml"),
        ("feature.schema.json", "feature.valid.md", "frontmatter"),
        ("result.schema.json", "result.valid.json", "json"),
        ("statement.schema.json", "statement.valid.json", "json"),
        ("pass.schema.json", "pass.valid.json", "json"),
        ("static-gates.schema.json", "static-gates.valid.json", "json"),
        ("rules.schema.json", "rules.valid.yaml", "yaml"),
        ("seed.schema.json", "seed.valid.yaml", "yaml"),
        ("waiver.schema.json", "waiver.valid.yaml", "yaml"),
    ]
    failed = False
    for schema_name, instance_name, kind in cases:
        instance_path = SCHEMAS / "examples" / instance_name
        if kind == "json":
            value = instance_path.read_text()
        elif kind == "yaml":
            value = yaml_to_json(instance_path)
        else:
            value = front_matter_to_json(instance_path)
        result = io_result(schema_name, value)
        if result != 0:
            failed = True
    print(f"validated {len(cases)} REV K examples")
    return 1 if failed else 0


def io_result(schema_name: str, value: str) -> int:
    instance = ROOT / ".asdi-example-instance.json"
    instance.write_text(value)
    import contextlib
    import io

    error = io.StringIO()
    with contextlib.redirect_stderr(error):
        result = validate(SCHEMAS / schema_name, instance)
    if result:
        print(error.getvalue(), file=sys.stderr)
    instance.unlink(missing_ok=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
