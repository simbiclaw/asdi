#!/usr/bin/env python3
"""Create the base-branch verifier fixture for the live Claude proxy probe."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


STATIC_GATES = """version: 1
checks:
  - id: probe-compile
    command: ["/usr/bin/python3", "-m", "py_compile", "proxy_probe.py"]
    blocking: true
    timeout_seconds: 30
policy:
  new_violations: reject
  legacy_findings: track_without_expanding
"""

PRODUCT = """name: live-proxy-probe
features:
  - live-egress-cli
"""

VERIFY = """#!/bin/sh
set -eu
TEST_ROOT=$(mktemp -d /tmp/asdi-verify.XXXXXX)
trap 'rm -rf "$TEST_ROOT"' EXIT
cp proxy_probe.py "$TEST_ROOT/proxy_probe.py"
mkdir -p "$TEST_ROOT/node_modules"
cp -a node_modules/. "$TEST_ROOT/node_modules/"
NORMAL=$(cd "$TEST_ROOT" && /usr/bin/python3 proxy_probe.py)
EXPECTED='{"git_clone":"pass","npm_package":"pass","model_endpoint":"configured"}'
if ! /usr/bin/python3 -c 'import json,sys; observed=json.loads(sys.argv[1]); expected={"git_clone":"pass","npm_package":"pass","model_endpoint":"configured"}; raise SystemExit(0 if observed == expected else 1)' "$NORMAL"; then
  printf 'normal probe mismatch: %s\\n' "$NORMAL" >&2
  exit 101
fi
CONTROL=$(/usr/bin/python3 /opt/base/verify/bin/control.py "$TEST_ROOT")
if [ "$CONTROL" = "$EXPECTED" ]; then
  printf 'negative control was not caught\\n' >&2
  exit 102
fi
if [ ! -f claude.stdout.log ] || [ ! -f claude.stderr.log ]; then
  printf 'missing Claude CLI logs\\n' >&2
  exit 103
fi
mkdir -p .asdi-evidence
printf '%s\\n' "$CONTROL" > .asdi-evidence/control-output.txt
cat > .asdi-evidence/result.json <<RESULT
{
  "schema": 2,
  "run_id": "$ASDI_RUN_ID",
  "commit": "$ASDI_COMMIT",
  "features": [
    {
      "id": "live-egress-cli",
      "status": "pass",
      "control": "caught",
      "evidence": ["claude.stdout.log", "claude.stderr.log", "control-output.txt"],
      "limits": ["Claude proxy transport probe; not production egress acceptance"]
    }
  ]
}
RESULT
"""

CONTROL = """from pathlib import Path
import shutil
import subprocess
import sys

root = Path(sys.argv[1]) / "control"
if root.exists():
    shutil.rmtree(root)
shutil.copytree(
    ".", root,
    ignore=lambda _src, names: ["control", ".asdi-evidence", "__pycache__"],
)
source = root / "proxy_probe.py"
source.write_text(source.read_text().replace('"git_clone":"pass"', '"git_clone":"control_broken"'))
completed = subprocess.run(
    ["/usr/bin/python3", str(source)], cwd=root, capture_output=True, text=True, check=False
)
print(completed.stdout, end="")
"""


def create_fixture(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    (destination / ".asdi").mkdir()
    (destination / "verify" / "bin").mkdir(parents=True)
    (destination / ".asdi" / "static-gates.yaml").write_text(STATIC_GATES)
    (destination / ".asdi" / "product.yaml").write_text(PRODUCT)
    verify = destination / "verify" / "bin" / "verify"
    verify.write_text(VERIFY)
    verify.chmod(0o755)
    (destination / "verify" / "bin" / "control.py").write_text(CONTROL)
    subprocess.run(["git", "init", "-b", "main", str(destination)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(destination), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git", "-C", str(destination),
            "-c", "user.name=ASDI", "-c", "user.email=asdi@local",
            "commit", "-m", "live proxy verifier fixture",
        ],
        check=True,
        capture_output=True,
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", nargs="?")
    arguments = parser.parse_args()
    if arguments.destination:
        destination = Path(arguments.destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        destination = Path(tempfile.mkdtemp(prefix="asdi-claude-live-probe-parent.", dir="/tmp")) / "product"
        destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        create_fixture(destination)
    except FileExistsError:
        parser.error(f"destination already exists: {destination}")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
