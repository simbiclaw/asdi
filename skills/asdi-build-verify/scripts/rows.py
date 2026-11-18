#!/usr/bin/env python3
"""List the requirements for one verification target, and optionally start a results file.

  rows.py --target phase-1                 # print the rows as a table
  rows.py --target phase-1 --json          # print them as JSON
  rows.py --target phase-1 --init DIR      # also write DIR/results.json to fill in
  rows.py --list                           # show every target in build order
"""
import sys
sys.dont_write_bytecode = True  # keep the skill folder unchanged
import argparse, datetime, json, os, sys
from common import load_register, normalise_target, select

ap = argparse.ArgumentParser()
ap.add_argument("--target")
ap.add_argument("--json", action="store_true")
ap.add_argument("--init", metavar="DIR")
ap.add_argument("--list", action="store_true")
a = ap.parse_args()
reg = load_register()

if a.list:
    print("Build order:", " -> ".join(reg["build_order"]))
    print("Pass 2 items:", ", ".join(reg["pass2_targets"]))
    print("Also: standing (the always-on rows only)")
    sys.exit(0)
if not a.target:
    ap.error("--target is required (or use --list)")

target = normalise_target(a.target)
rows = select(reg, target)

if a.init:
    os.makedirs(os.path.join(a.init, "evidence"), exist_ok=True)
    path = os.path.join(a.init, "results.json")
    if os.path.exists(path):
        raise SystemExit("%s already exists; refusing to overwrite a verification record" % path)
    skeleton = {
        "target": target,
        "spec_revision": reg["spec"]["revision"],
        "guide_version": reg["spec"]["guide_version"],
        "repo": "",
        "commit": "",
        "verifier": {"agent": "", "built_this_target_in_same_session": None},
        "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "finished": "",
        "results": [{"id": r["id"], "status": "", "control": "", "observed": "",
                     "evidence": [], "limits": []} for r in rows],
        "claims": [],
        "notes": [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(skeleton, f, indent=1)
    print("Wrote", path, "with", len(rows), "rows to fill in.\n")

if a.json:
    print(json.dumps(rows, indent=1, ensure_ascii=False))
else:
    print("Target: %s   Spec revision: %s   Rows: %d\n" % (target, reg["spec"]["revision"], len(rows)))
    for r in rows:
        needs = (" [needs: %s]" % ", ".join(r["needs"])) if r["needs"] else ""
        print("%s  (%s, %s)%s" % (r["id"], r["method"], r["source"], needs))
        print("  Requirement: " + r["statement"])
        print("  How: " + r["how"])
        if r["control"]:
            print("  Control: " + r["control"])
        print()
