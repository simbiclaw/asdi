"""Shared helpers for the asdi-build-verify scripts. Standard library only."""
import hashlib, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:  # works under `python3 -I` and from any working directory
    sys.path.insert(0, HERE)
REGISTER = os.path.join(HERE, "..", "references", "register.json")
STATUSES = ["pass", "fail", "blocked", "error", "not_applicable"]
SPEC_DIR_CANDIDATES = ("reference", "docs/spec", "spec", "docs")
# Files the scanners read as text. "" (no extension) is deliberately absent: matching
# every path with endswith("") made the scanners read binaries and archives.
TEXT_EXT = {".py", ".sh", ".md", ".yaml", ".yml", ".json", ".toml", ".ts", ".js", ".env", ".txt", ".cfg", ".ini"}
TEXT_NAMES = {"Dockerfile", "Makefile", ".env", "Vagrantfile"}
# Rows an owner decision may never override (Guide §9.5 "never waivable", plus the
# rows that protect this verification itself).
NEVER_OVERRIDE = {"HR-1", "HR-3", "HR-4", "HR-6", "C-5", "ST-SPEC-1", "ST-SEC-1",
                  "ST-INJECT-1", "ST-CLAIM-1", "PR-TEST-1", "PR-PROT-1"}


def load_register():
    with open(REGISTER, encoding="utf-8") as f:
        return json.load(f)


def is_text(path):
    base = os.path.basename(path)
    return base in TEXT_NAMES or os.path.splitext(base)[1].lower() in TEXT_EXT


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def authority(repo="."):
    """The authoritative spec set pinned in reference/AUTHORITY.md, if the repo has one.

    Returns {"file": path, "specs": [{"role", "path", "sha256"}]} or None.
    """
    path = os.path.join(repo, "reference", "AUTHORITY.md")
    if not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    section = text.split("## Authoritative specification set", 1)[-1].split("\n## ", 1)[0]
    specs = []
    for line in section.splitlines():
        m = re.match(r"\|\s*(.+?)\s*\|\s*\[`([^`]+)`\]\(([^)]+)\)\s*\|\s*`([0-9a-f]{64})`\s*\|", line)
        if m:
            name = m.group(2)
            specs.append({"role": m.group(1), "path": os.path.join("reference", name), "sha256": m.group(4)})
    return {"file": "reference/AUTHORITY.md", "specs": specs}


def find_spec_dir(repo=".", given=None):
    if given:
        return given
    if authority(repo):
        return "reference"
    return next((d for d in SPEC_DIR_CANDIDATES if os.path.isdir(os.path.join(repo, d))), "docs/spec")


def owner_overrides(repo="."):
    """Owner decisions recorded in DECISIONS.md: {"DD-48": "row text", ...}.

    A verifier may cite one of these on a failing row (results row field
    "override": "DD-48"). report.py accepts the citation only if the ID exists
    here and the row is not in NEVER_OVERRIDE.
    """
    path = os.path.join(repo, "DECISIONS.md")
    if not os.path.exists(path):
        return {}
    out = {}
    for line in open(path, encoding="utf-8").read().splitlines():
        m = re.match(r"\|\s*(D{1,2}-\d+|REV-[A-Z])\s*\|(.*)", line)
        if m and "owner" in m.group(2).lower():
            out[m.group(1)] = m.group(2).strip()
    return out


def git(repo, *args, timeout=60):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)


def normalise_target(t):
    t = t.strip().lower().replace("_", "-").replace(" ", "-")
    m = re.fullmatch(r"(?:phase-?)?(\d+)", t)
    if m:
        return "phase-" + m.group(1)
    m = re.fullmatch(r"p(?:ass)?-?2-(\d+)", t)
    if m:
        return "p2-" + m.group(1)
    return {"firstlight": "first-light", "fullloop": "full-loop", "gate": "deploy-gate"}.get(t, t)


def select(reg, target, phase=None):
    """Rows for a target: its own rows plus every standing row that applies by then.

    target "pr" is the PR gate profile: the PR rows, plus the standing rows that can
    be decided from the repository and git alone at the phase the repo is in
    (``phase``), minus the rows that judge a whole phase rather than one change.
    """
    order = reg["build_order"]
    if target == "pr":
        pos = order.index(phase) if phase in order else 0
        rows = [r for r in reg["requirements"] if r.get("target") == "pr"]
        for r in reg["requirements"]:
            if (r["kind"] == "standing" and order.index(r["applies_from"]) <= pos
                    and r["method"] == "inspect" and set(r["needs"]) <= {"git"}
                    and r["id"] not in reg.get("pr_excluded_standing", [])):
                rows.append(r)
        return rows
    if target == "standing":
        pos = len(order)
    elif target in order:
        pos = order.index(target)
    elif target in reg["pass2_targets"]:
        pos = len(order)
    else:
        raise SystemExit("Unknown target %r. Use one of: %s, %s, standing, pr"
                         % (target, ", ".join(order), ", ".join(reg["pass2_targets"])))
    rows = []
    for r in reg["requirements"]:
        if r["kind"] == "standing":
            if order.index(r["applies_from"]) <= pos:
                rows.append(r)
        elif r.get("target") == target:
            rows.append(r)
    return rows
