#!/usr/bin/env python3
"""Settle one row of a results.json after opening its leads yourself.

  confirm.py DIR ROW --status pass|fail|blocked|error|not_applicable --observed "..."
             [--evidence PATH ...] [--control caught|missed] [--limit TEXT ...] [--override DECISION-ID]

Clears needs_confirmation and records that the verifier, not pr_check.py, decided it.
It never changes the verdict rules: report.py still checks evidence, controls and overrides.
"""
import sys, os
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse, json
from common import STATUSES


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("row")
    ap.add_argument("--status", required=True, choices=STATUSES)
    ap.add_argument("--observed", required=True)
    ap.add_argument("--evidence", nargs="*", default=None)
    ap.add_argument("--control", choices=["caught", "missed", ""])
    ap.add_argument("--limit", nargs="*", default=None)
    ap.add_argument("--override")
    a = ap.parse_args(argv)
    path = os.path.join(a.dir, "results.json")
    res = json.load(open(path, encoding="utf-8"))
    row = next((r for r in res["results"] if r["id"] == a.row), None)
    if row is None:
        raise SystemExit("%s is not a row of this record" % a.row)
    row.update(status=a.status, observed=a.observed, needs_confirmation=False, decided_by="verifier")
    if a.evidence is not None:
        row["evidence"] = a.evidence
    if a.control is not None:
        row["control"] = a.control
    if a.limit is not None:
        row["limits"] = a.limit
    if a.override:
        row["override"] = a.override
    json.dump(res, open(path, "w", encoding="utf-8"), indent=1)
    print("%s: %s" % (a.row, a.status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
