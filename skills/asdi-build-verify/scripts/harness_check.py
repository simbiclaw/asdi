#!/usr/bin/env python3
"""Static check of a product repo's ASDI harness (guide §6). Produces leads for P3-1, P3-2, P3-3, P3-7.

  harness_check.py --product-repo ../toy-notes

It reads files only. It does not run the harness: P3-4 and P3-5 need you to run
verify launch / doctor / drive / control / cleanup yourself in a scratch copy.
"""
import sys
sys.dont_write_bytecode = True  # keep the skill folder unchanged
import argparse, json, os, re

ap = argparse.ArgumentParser()
ap.add_argument("--product-repo", required=True)
a = ap.parse_args()
repo = os.path.abspath(a.product_repo)
leads, info = [], {}


def lead(row, detail, where=""):
    leads.append({"row": row, "detail": detail, "where": where})


def read(p):
    try:
        return open(os.path.join(repo, p), encoding="utf-8", errors="replace").read()
    except OSError:
        return None


try:
    import yaml
except ImportError:
    yaml = None
    info["yaml"] = "PyYAML not installed: feature front matter and manifests were not parsed. Read them by hand."

for p in ["AGENTS.md", "CLAUDE.md", ".asdi/product.yaml", ".asdi/static-gates.yaml", "verify/SKILL.md",
          "verify/verify.yaml", "verify/bin/verify", "verify/features"]:
    if not os.path.exists(os.path.join(repo, p)):
        lead("P3-1", "missing: " + p, p)
c = read("CLAUDE.md")
if c is not None and c.strip() != "@AGENTS.md":
    lead("P3-1", "CLAUDE.md is not the single line @AGENTS.md", "CLAUDE.md")
v = os.path.join(repo, "verify/bin/verify")
if os.path.exists(v) and not os.access(v, os.X_OK):
    lead("P3-1", "verify/bin/verify is not executable", "verify/bin/verify")

features, kinds, patterns = [], set(), []
fdir = os.path.join(repo, "verify/features")
if os.path.isdir(fdir) and yaml:
    for n in sorted(os.listdir(fdir)):
        if not n.endswith(".md"):
            continue
        t = read("verify/features/" + n) or ""
        m = re.match(r"(?s)^---\n(.*?)\n---", t)
        where = "verify/features/" + n
        if not m:
            lead("P3-2", "no front matter", where)
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except Exception as e:  # noqa
            lead("P3-2", "front matter does not parse: %s" % e, where)
            continue
        features.append(fm.get("id", n))
        for key in ("id", "paths", "drive", "proof", "negative_control"):
            if not fm.get(key):
                lead("P3-2", "feature has no %s" % key, where)
        if "limits" not in fm:
            lead("P3-2", "feature states no limits (an empty list is allowed, a missing key is not)", where)
        k = (fm.get("drive") or {}).get("kind") if isinstance(fm.get("drive"), dict) else None
        if k:
            kinds.add(k)
        patterns += [str(p) for p in (fm.get("paths") or [])]
    info["features"] = features
    info["drive_kinds"] = sorted(kinds)
    if len(features) < 3:
        lead("P3-2", "only %d feature file(s); the guide asks for at least three" % len(features), "verify/features")
    for need in ("cli", "http", "ui"):
        if need not in kinds:
            lead("P3-2", "no feature with drive kind %s" % need, "verify/features")


def to_rx(glob):
    out, i = "", 0
    while i < len(glob):
        if glob[i:i + 3] == "**/":
            out += "(?:.*/)?"; i += 3
        elif glob[i:i + 2] == "**":
            out += ".*"; i += 2
        elif glob[i] == "*":
            out += "[^/]*"; i += 1
        elif glob[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(glob[i]); i += 1
    return re.compile("^" + out + "$")


if patterns:
    rx = [to_rx(p) for p in patterns]
    NOT_SOURCE = ("verify/", "evals/", ".asdi/", ".git/", "docs/", "tests/", "test/", "node_modules/", "fixtures/")
    uncovered = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for n in names:
            r = os.path.relpath(os.path.join(root, n), repo)
            if r.startswith(NOT_SOURCE) or "/" not in r or n.endswith((".md", ".lock", ".toml", ".cfg")):
                continue
            if not any(x.match(r) for x in rx):
                uncovered.append(r)
    info["uncovered_files"] = uncovered[:200]
    for r in uncovered[:50]:
        lead("P3-3", "source file belongs to no feature", r)

sg = read(".asdi/static-gates.yaml")
if sg and yaml:
    try:
        doc = yaml.safe_load(sg) or {}
        checks = doc.get("checks") or []
        info["static_gates"] = [c.get("id") for c in checks if isinstance(c, dict)]
        if not 3 <= len(checks) <= 4:
            lead("P3-7", "%d checks declared; the guide asks for three or four in Pass 1" % len(checks), ".asdi/static-gates.yaml")
        for c in checks:
            for key in ("id", "command", "blocking", "timeout_seconds"):
                if not isinstance(c, dict) or key not in c:
                    lead("P3-7", "a check has no %s" % key, ".asdi/static-gates.yaml")
    except Exception as e:  # noqa
        lead("P3-7", "static-gates.yaml does not parse: %s" % e, ".asdi/static-gates.yaml")

print(json.dumps({"leads": leads, "info": info,
                  "reminder": "Static leads only. The harness still has to be run: see P3-4 and P3-5."}, indent=1))
