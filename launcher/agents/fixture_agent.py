#!/usr/bin/env python3
"""Container fixture used only by REV K Phase 1 launcher tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--commit", required=True)
    arguments = parser.parse_args()
    workspace = Path(arguments.workspace)
    (workspace / "src" / "generated.py").write_text("VALUE = 'generated'\n")
    evidence = Path("/evidence")
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "agent.log").write_text("fixture completed\n")
    result = {
        "schema": 2,
        "run_id": arguments.run_id,
        "commit": arguments.commit,
        "features": [
            {
                "id": "generated-module",
                "status": "pass",
                "control": "caught",
                "evidence": ["agent.log"],
                "limits": ["container fixture only"],
            }
        ],
    }
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
