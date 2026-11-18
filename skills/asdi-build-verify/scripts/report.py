#!/usr/bin/env python3
"""Check a filled-in results.json, work out the verdict, and write REPORT.md and verdict.json.

  report.py DIR            # DIR holds results.json and evidence/

The verdict is computed here, not chosen by the verifier:
  NOT VERIFIED  any row failed
  INCOMPLETE    nothing failed, but a row is blocked, in error, unchecked or badly recorded
  VERIFIED      every row passed or is not applicable, each pass has evidence and its control

Owner overrides: a failing row may carry "override": "<decision ID>". It is accepted
only if the ID is an owner decision in DECISIONS.md (for target "pr": the base
commit's DECISIONS.md, captured by pr_check.py, so a PR cannot add its own) and the
row is not in NEVER_OVERRIDE. Accepted overrides are listed first in the report and
do not fail the verdict; anything else about them is a problem with the record.

A row prefilled with "needs_confirmation": true must be settled by the verifier
(status set, and needs_confirmation set to false) before a verdict is possible.
"""
import sys, os
sys.dont_write_bytecode = True  # keep the skill folder unchanged
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collections, json
from common import NEVER_OVERRIDE, load_register, owner_overrides, select, STATUSES

if len(sys.argv) != 2:
    raise SystemExit(__doc__)
d = sys.argv[1]
res = json.load(open(os.path.join(d, "results.json"), encoding="utf-8"))
reg = load_register()
rows = {r["id"]: r for r in select(reg, res["target"], res.get("phase"))}
if res["target"] == "pr":
    decisions = res.get("base_owner_decisions", {})
else:
    decisions = owner_overrides(res["repo"]) if res.get("repo") and os.path.isdir(res["repo"]) else {}
overridden = {}
got = {r["id"]: r for r in res.get("results", [])}
problems = []

for rid in rows:
    if rid not in got:
        problems.append("%s: no result recorded" % rid)
for rid, r in got.items():
    if rid not in rows:
        problems.append("%s: not a row for target %s" % (rid, res["target"]))
        continue
    spec = rows[rid]
    s = r.get("status", "")
    if r.get("needs_confirmation"):
        problems.append("%s: prefilled leads not yet confirmed; open them, set the status, then set "
                        "needs_confirmation to false" % rid)
        continue
    if s not in STATUSES:
        problems.append("%s: status %r is not one of %s" % (rid, s, ", ".join(STATUSES)))
        continue
    if r.get("override"):
        oid = r["override"]
        if s != "fail":
            problems.append("%s: an override is only meaningful on a failing row" % rid)
        elif rid in NEVER_OVERRIDE:
            problems.append("%s: this row can never be overridden (Guide §9.5)" % rid)
        elif oid not in decisions:
            problems.append("%s: override %s is not an owner decision in %s DECISIONS.md"
                            % (rid, oid, "the base commit's" if res["target"] == "pr" else "the repo's"))
        else:
            overridden[rid] = oid
    if not r.get("observed", "").strip():
        problems.append("%s: 'observed' is empty; say what you saw or why it does not apply" % rid)
    if s == "pass":
        if not r.get("evidence"):
            problems.append("%s: pass with no evidence" % rid)
        if spec["control"] and r.get("control") != "caught":
            problems.append("%s: pass, but its control was not shown as caught (%r)" % (rid, r.get("control", "")))
    for e in r.get("evidence", []):
        name = e.split("#")[0].split(":")[0].strip()
        if e.startswith("evidence/"):
            if not os.path.exists(os.path.join(d, name)):
                problems.append("%s: evidence file %s does not exist" % (rid, e))
        elif (res.get("repo") and os.path.isdir(res["repo"]) and "://" not in e and " " not in name
              and ("/" in name or "." in name)):
            if not os.path.exists(os.path.join(res["repo"], name)):
                problems.append("%s: evidence refers to %s, which is not in the repo" % (rid, name))

counts = collections.Counter("overridden" if r["id"] in overridden else r.get("status", "")
                             for r in got.values() if r["id"] in rows)
unconfirmed = [c for c in res.get("claims", []) if not c.get("verified")]
if unconfirmed and got.get("ST-CLAIM-1", {}).get("status") == "pass":
    problems.append("ST-CLAIM-1 is recorded as pass, but %d builder claim(s) are marked unconfirmed" % len(unconfirmed))
if ("ST-CLAIM-1" in rows and res["target"] != "pr" and not res.get("claims")
        and got.get("ST-CLAIM-1", {}).get("status") == "pass"):
    problems.append("ST-CLAIM-1 is recorded as pass, but the claims list is empty")
if counts["fail"]:  # overridden rows are counted separately, never as "fail"
    verdict = "NOT VERIFIED"
elif problems or counts["blocked"] or counts["error"] or counts[""]:
    verdict = "INCOMPLETE"
else:
    verdict = "VERIFIED"


def cell(x):
    return str(x).replace("|", "\\|").replace("\n", " ")


L = []
L.append("# ASDI build verification: %s" % res["target"])
L.append("")
L.append("**Verdict: %s**" % verdict)
L.append("")
L.append("- Spec revision: REV %s, guide %s" % (res.get("spec_revision", "?"), res.get("guide_version", "?")))
L.append("- Repo: %s at %s" % (res.get("repo") or "?", res.get("commit") or "?"))
v = res.get("verifier", {})
L.append("- Verifier: %s%s" % (v.get("agent") or "?",
         " (the same session built this target: independence not met)" if v.get("built_this_target_in_same_session") else ""))
L.append("- Started %s, finished %s" % (res.get("started", "?"), res.get("finished") or "?"))
if res.get("base"):
    L.append("- Base: %s (target pr: judges this change only; not a phase acceptance)" % res["base"])
L.append("- Rows: " + ", ".join("%d %s" % (counts[s], s) for s in STATUSES + ["overridden"] if counts[s]) +
         (", %d unrecorded" % counts[""] if counts[""] else ""))
L.append("")


def table(title, pick, cols):
    sel = [got[i] for i in rows if i in got and pick(got[i])]
    if not sel:
        return
    L.append("## " + title)
    L.append("")
    L.append("| Row | Requirement | " + " | ".join(c[0] for c in cols) + " |")
    L.append("|---|---|" + "---|" * len(cols))
    for r in sel:
        L.append("| %s | %s | %s |" % (r["id"], cell(rows[r["id"]]["statement"]),
                 " | ".join(cell(c[1](r)) for c in cols)))
    L.append("")


ev = lambda r: "; ".join(r.get("evidence", [])) or "none"
table("Failed", lambda r: r["status"] == "fail" and r["id"] not in overridden,
      [("Observed", lambda r: r.get("observed", "")), ("Evidence", ev)])
table("Failed but covered by an owner decision", lambda r: r["id"] in overridden,
      [("Decision", lambda r: overridden[r["id"]]), ("Observed", lambda r: r.get("observed", ""))])
table("Blocked or in error", lambda r: r["status"] in ("blocked", "error"),
      [("Status", lambda r: r["status"]), ("Why", lambda r: r.get("observed", ""))])
if unconfirmed:
    L.append("## Builder claims not confirmed")
    L.append("")
    L.append("| Claim | Where it is made | Row | What this run found |")
    L.append("|---|---|---|---|")
    for c in unconfirmed:
        L.append("| %s | %s | %s | %s |" % (cell(c.get("claim", "")), cell(c.get("source", "")),
                 cell(c.get("row", "")), cell(c.get("found", ""))))
    L.append("")
if problems:
    L.append("## Problems with this record")
    L.append("")
    L.extend("- " + p for p in problems)
    L.append("")
lim = [(r["id"], l) for r in got.values() for l in r.get("limits", [])]
if lim or res.get("notes"):
    L.append("## Limits and notes")
    L.append("")
    L.extend("- %s: %s" % x for x in lim)
    L.extend("- " + n for n in res.get("notes", []))
    L.append("")
table("Passed", lambda r: r["status"] == "pass",
      [("Control", lambda r: r.get("control", "") or "n/a"), ("Observed", lambda r: r.get("observed", "")), ("Evidence", ev)])
table("Not applicable", lambda r: r["status"] == "not_applicable", [("Why", lambda r: r.get("observed", ""))])

open(os.path.join(d, "REPORT.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
def detail(r):
    spec = rows[r["id"]]
    return {"id": r["id"], "status": r.get("status"), "statement": spec["statement"], "source": spec["source"],
            "observed": r.get("observed", ""), "evidence": r.get("evidence", []), "leads": r.get("leads", []),
            "needs": spec.get("needs", []), "override": overridden.get(r["id"])}


pick = lambda f: [detail(got[i]) for i in rows if i in got and f(got[i])]
json.dump({"target": res["target"], "verdict": verdict, "counts": dict(counts), "problems": problems,
           "spec_revision": res.get("spec_revision"), "commit": res.get("commit"), "base": res.get("base"),
           "phase": res.get("phase"),
           "failed": pick(lambda r: r.get("status") == "fail" and r["id"] not in overridden),
           "overridden": pick(lambda r: r["id"] in overridden),
           "blocked": pick(lambda r: r.get("status") in ("blocked", "error", "")),
           "unconfirmed_claims": unconfirmed, "notes": res.get("notes", [])},
          open(os.path.join(d, "verdict.json"), "w"), indent=1)
print("Verdict:", verdict)
print("Rows:", dict(counts))
if problems:
    print("Problems with the record (fix the record, never the verdict):")
    for p in problems:
        print(" -", p)
print("Wrote", os.path.join(d, "REPORT.md"))
