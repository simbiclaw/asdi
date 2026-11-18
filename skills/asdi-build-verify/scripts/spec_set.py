#!/usr/bin/env python3
"""Find the four ASDI specs and check they belong to one revision.

  spec_set.py [--spec-dir DIR]     # without --spec-dir it tries docs/spec, spec, docs
Prints JSON. Exit code 0 if four specs share one revision that matches the register, else 1.

This answers ST-SPEC-1 only (present, one revision). It says nothing about whether
someone edited the specs: that is ST-SPEC-2, checked with git.
"""
import sys
sys.dont_write_bytecode = True  # keep the skill folder unchanged
import argparse, collections, json, os, re, sys
from common import load_register

KINDS = {"design": ["design"], "stack": ["stack"], "guide": ["guide"], "handbook": ["handbook"]}


def text_of(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    raw = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", raw)
    return re.sub(r"(?s)<[^>]+>", " ", raw)


ap = argparse.ArgumentParser()
ap.add_argument("--spec-dir")
a = ap.parse_args()
if not a.spec_dir:
    a.spec_dir = next((d for d in ("docs/spec", "spec", "docs") if os.path.isdir(d)), "docs/spec")
reg = load_register()
out = {"spec_dir": a.spec_dir, "specs": {}, "problems": [], "warnings": [],
       "scope": "ST-SPEC-1 only: present and one revision. Whether the specs were edited is ST-SPEC-2 (git)."}

files = []
if os.path.isdir(a.spec_dir):
    for n in sorted(os.listdir(a.spec_dir)):
        if n.lower().endswith((".html", ".htm", ".md")):
            files.append(os.path.join(a.spec_dir, n))
else:
    out["problems"].append("spec directory not found")

for kind, keys in KINDS.items():
    hit = [f for f in files if any(k in os.path.basename(f).lower() for k in keys)]
    if not hit:
        out["problems"].append("no %s spec found" % kind)
        continue
    if len(hit) > 1:
        out["problems"].append("more than one %s spec: %s" % (kind, ", ".join(map(os.path.basename, hit))))
    t = text_of(hit[0])
    head = t[:6000]
    revs = collections.Counter(re.findall(r"\bREV\s+([A-Z])\b", head))
    rev = revs.most_common(1)[0][0] if revs else None
    ver = re.search(r"\b[vV](\d+)\b", head)
    out["specs"][kind] = {"file": hit[0], "revision": rev, "version": ("v" + ver.group(1)) if ver else None}
    if rev is None:
        out["problems"].append("%s spec states no revision" % kind)
    if os.path.getsize(hit[0]) < 4000:
        out["warnings"].append("%s spec is only %d bytes; it may be an excerpt, so rows citing it cannot be checked against it"
                               % (kind, os.path.getsize(hit[0])))

revs = {k: v["revision"] for k, v in out["specs"].items()}
if len(set(revs.values())) > 1:
    out["problems"].append("specs carry different revisions: %s" % revs)
out["register_revision"] = reg["spec"]["revision"]
if revs and set(revs.values()) == {reg["spec"]["revision"]}:
    out["register_matches"] = True
else:
    out["register_matches"] = False
    if len(set(revs.values())) == 1:
        out["problems"].append("specs are at revision %s but this skill's register was written for %s; "
                               "read the cited spec sections for every row and treat the spec text as the authority"
                               % (list(revs.values())[0], reg["spec"]["revision"]))
out["consistent"] = not out["problems"]
print(json.dumps(out, indent=1))
sys.exit(0 if out["consistent"] else 1)
