#!/usr/bin/env python3
"""Deterministic local stand-in for a real implementation agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


GOOD_APP = '''\
#!/usr/bin/env python3
import argparse
import json

APP_REVISION = "__REVISION__"


def handle(scenario: str, enabled: bool) -> dict:
    if scenario == "normal":
        return {"ok": True, "variant": "on" if enabled else "off", "revision": APP_REVISION}
    if scenario == "load":
        return {"ok": True, "variant": "on" if enabled else "off", "revision": APP_REVISION}
    return {"ok": False, "error": "unknown scenario"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--handle", action="store_true")
    parser.add_argument("--scenario", default="normal")
    parser.add_argument("--flag-enabled", default="false")
    arguments = parser.parse_args()
    enabled = arguments.flag_enabled.lower() == "true"
    if arguments.self_check:
        result = {"ok": handle("normal", False)["ok"] and handle("load", False)["ok"], "revision": APP_REVISION}
    elif arguments.handle:
        result = handle(arguments.scenario, enabled)
    else:
        result = {"ok": False, "error": "no operation"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


BUGGY_APP = GOOD_APP.replace(
    '        return {"ok": True, "variant": "on" if enabled else "off", "revision": APP_REVISION}\n    return {"ok": False, "error": "unknown scenario"}',
    '        if enabled:\n            return {"ok": False, "error": "load-handling defect", "revision": APP_REVISION}\n        return {"ok": True, "variant": "off", "revision": APP_REVISION}\n    return {"ok": False, "error": "unknown scenario"}',
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--variant", choices=("good", "buggy", "repair"), required=True)
    arguments = parser.parse_args()
    workspace = Path(arguments.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    revision = {
        "good": "prototype_feature_v1",
        "buggy": "prototype_load_v2_defective",
        "repair": "prototype_load_v3_repaired",
    }[arguments.variant]
    app_source = GOOD_APP.replace("__REVISION__", revision)
    if arguments.variant == "buggy":
        app_source = BUGGY_APP.replace("__REVISION__", revision)
    (workspace / "app.py").write_text(app_source)
    (workspace / "manifest.json").write_text(
        json.dumps(
            {
                "mission_id": arguments.mission_id,
                "variant": arguments.variant,
                "revision": revision,
                "paths": ["app.py"],
                "fixture_agent": True,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(json.dumps({"ok": True, "variant": arguments.variant, "revision": revision}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
