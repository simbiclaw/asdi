#!/usr/bin/env python3
"""Find the four ASDI specs and check they belong to one revision.

  spec_set.py [--repo .] [--spec-dir DIR]
Prints JSON. Exit code 0 if four specs share one revision that matches the register, else 1.

If the repo pins its authority set in reference/AUTHORITY.md, that file decides which
four documents are the specs, and each one's SHA-256 must match its pin: a mismatch
means a spec was edited after it was pinned (evidence for ST-SPEC-2 as well).
Supplemental documents that merely mention "guide" are not mistaken for the Build Guide.
Without AUTHORITY.md it falls back to looking in reference/, docs/spec, spec, docs.

This answers ST-SPEC-1 (present, one revision) and, with pins, whether the files
still match them. Who changed a spec, and when, is ST-SPEC-2 with git.
"""
import sys, os
sys.dont_write_bytecode = True  # keep the skill folder unchanged
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse, collections, json, re
from common import authority, find_spec_dir, load_register, sha256

KINDS = {"design": ["design"], "stack": ["stack"], "guide": ["build-guide", "build guide", "guide"],
         "handbook": ["handbook"]}
ROLE_KIND = [("product intent", "design"), ("components", "stack"), ("normative implementation", "guide"),
             ("trust model", "handbook")]


def text_of(path):
    raw = open(path, encoding="utf-8", errors="replace").read()
    raw = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", raw)
    return re.sub(r"(?s)<[^>]+>", " ", raw)


def revision_of(path):
    head = text_of(path)[:6000]
    revs = collections.Counter(re.findall(r"\bREV\s+([A-Z])\b", head))
    ver = re.search(r"\b[vV](\d+)\b", head)
    return (revs.most_common(1)[0][0] if revs else None), (("v" + ver.group(1)) if ver else None)


def kind_of_role(role):
    low = role.lower()
    return next((k for key, k in ROLE_KIND if key in low), None)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--spec-dir")
    a = ap.parse_args(argv)
    reg = load_register()
    out = {"specs": {}, "problems": [], "warnings": [],
           "scope": "ST-SPEC-1: present and one revision; with AUTHORITY.md pins, also unchanged since pinning."}
    pins = None if a.spec_dir else authority(a.repo)
    if pins and len(pins["specs"]) == 4:
        out["authority"] = pins["file"]
        for spec in pins["specs"]:
            kind = kind_of_role(spec["role"]) or spec["role"]
            path = os.path.join(a.repo, spec["path"])
            if not os.path.exists(path):
                out["problems"].append("%s spec pinned in AUTHORITY.md is missing: %s" % (kind, spec["path"]))
                continue
            rev, ver = revision_of(path)
            actual = sha256(path)
            out["specs"][kind] = {"file": spec["path"], "revision": rev, "version": ver,
                                  "sha256": actual, "pinned_sha256": spec["sha256"], "matches_pin": actual == spec["sha256"]}
            if actual != spec["sha256"]:
                out["problems"].append("%s spec does not match its AUTHORITY.md pin (edited after pinning): %s"
                                       % (kind, spec["path"]))
            if rev is None:
                out["problems"].append("%s spec states no revision" % kind)
    else:
        if pins:
            out["warnings"].append("AUTHORITY.md found but it does not pin exactly four specs; falling back to file names")
        spec_dir = find_spec_dir(a.repo, a.spec_dir)
        out["spec_dir"] = spec_dir
        base = os.path.join(a.repo, spec_dir)
        files = []
        if os.path.isdir(base):
            files = [os.path.join(base, n) for n in sorted(os.listdir(base))
                     if n.lower().endswith((".html", ".htm", ".md"))]
        else:
            out["problems"].append("spec directory not found: %s" % spec_dir)
        for kind, keys in KINDS.items():
            names = lambda f: os.path.basename(f).lower()
            hit = [f for f in files if any(k in names(f) for k in keys)]
            if kind == "guide":  # the Build Guide, not a supplemental "...Skill-Build-Guide"
                strict = [f for f in hit if "skill" not in names(f) and "verification" not in names(f)]
                hit = strict or hit
            if not hit:
                out["problems"].append("no %s spec found" % kind)
                continue
            if len(hit) > 1:
                out["problems"].append("more than one %s spec: %s" % (kind, ", ".join(map(os.path.basename, hit))))
            rev, ver = revision_of(hit[0])
            out["specs"][kind] = {"file": os.path.relpath(hit[0], a.repo), "revision": rev, "version": ver}
            if rev is None:
                out["problems"].append("%s spec states no revision" % kind)
    for kind, spec in out["specs"].items():
        size = os.path.getsize(os.path.join(a.repo, spec["file"]))
        if size < 4000:
            out["warnings"].append("%s spec is only %d bytes; it may be an excerpt, so rows citing it cannot be "
                                   "checked against it" % (kind, size))
    revs = {k: v["revision"] for k, v in out["specs"].items()}
    if len(set(revs.values())) > 1:
        out["problems"].append("specs carry different revisions: %s" % revs)
    out["register_revision"] = reg["spec"]["revision"]
    out["register_matches"] = bool(revs) and set(revs.values()) == {reg["spec"]["revision"]}
    if revs and not out["register_matches"] and len(set(revs.values())) == 1:
        out["problems"].append("specs are at revision %s but this skill's register was written for %s; read the "
                               "cited spec sections for every row and treat the spec text as the authority"
                               % (list(revs.values())[0], reg["spec"]["revision"]))
    out["consistent"] = not out["problems"] and len(out["specs"]) == 4
    print(json.dumps(out, indent=1))
    return 0 if out["consistent"] else 1


if __name__ == "__main__":
    sys.exit(main())
