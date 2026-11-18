#!/usr/bin/env python3
"""Static scan of an ASDI repo. Produces LEADS for the standing rows, not verdicts.

  repo_scan.py --repo . --target phase-1 [--spec-dir DIR]

The spec directory defaults to the one reference/AUTHORITY.md pins (else reference/,
docs/spec, spec, docs). It is not scanned: specs describe forbidden things by name,
which would only produce noise leads.

Every lead names the row it bears on and a place to look. Open that place and
confirm before recording a status: a pattern match is not evidence on its own,
and a clean scan does not prove a row passes.
"""
import sys, os
sys.dont_write_bytecode = True  # keep the skill folder unchanged
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse, json, re, subprocess
from common import find_spec_dir, is_text, load_register, normalise_target, owner_overrides

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "verification", ".asdi-state"}
SKIP_PATHS = ("skills/asdi-build-verify", "reference/archive")
EARLY_SERVICES = ["signer", "package-proxy", "probe-runner", "growthbook"]
EARLY_PATHS = ["infra/package-proxy", "probes", "evidence/attest", "config/waivers.yaml", "config/seeds.yaml"]
EARLY_WORDS = [("seed-suite", r"seed[-_ ]suite"), ("skill-eval", r"skill[-_ ]eval"), ("drift sweep", r"drift[-_ ]sweep"),
               ("merge queue", r"merge_group|gh-readonly-queue|merge[-_ ]queue"), ("pause/resume", r"\bdef (pause|resume)\b|launcher (pause|resume)"),
               ("four review passes", r"blast[-_ ]radius")]
SECRET_RX = [("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{20,}"), ("GitHub fine-grained token", r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
             ("Anthropic key", r"\bsk-ant-[A-Za-z0-9_-]{16,}"), ("API key", r"\bsk-[A-Za-z0-9]{24,}"),
             ("AWS key id", r"\bAKIA[0-9A-Z]{16}\b"), ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]
INJECT_RX = re.compile(r"(?i)\b(verifier|reviewer|auditor)s?\b[^.\n]{0,80}\b(mark|record|treat|skip|ignore|approve|assume|do not (check|run|verify))\b"
                       r"|\b(mark|record|treat)\b[^.\n]{0,40}\bas (pass|passed|verified|green)\b")
LAYOUT = [("phase-0", ["compose.yaml", "config", "schemas", "AGENTS.md", "CLAUDE.md", "STATUS.md", "DECISIONS.md", "ASSUMPTIONS.md"]),
          ("phase-1", ["launcher", "launcher/agents", "evidence", "infra/egress"]),
          ("phase-4", ["events", "archon", "merge", "tests/rules"]),
          ("phase-7", ["deploy", "backup", "ci"]),
          ("phase-2", ["board"]),
          ("phase-8", ["exposure"])]

ap = argparse.ArgumentParser()
ap.add_argument("--repo", default=".")
ap.add_argument("--target", required=True)
ap.add_argument("--spec-dir")
a = ap.parse_args()
a.spec_dir = find_spec_dir(a.repo, a.spec_dir)
reg = load_register()
order = reg["build_order"]
target = normalise_target(a.target)
pos = order.index(target) if target in order else len(order)
repo = os.path.abspath(a.repo)
leads, info = [], {}


def lead(row, detail, where=""):
    leads.append({"row": row, "detail": detail, "where": where})


def rel(p):
    return os.path.relpath(p, repo)


skip_abs = {os.path.abspath(os.path.join(repo, p)) for p in (a.spec_dir,) + SKIP_PATHS}
files = []
for root, dirs, names in os.walk(repo):
    dirs[:] = [x for x in dirs if x not in SKIP_DIRS and os.path.abspath(os.path.join(root, x)) not in skip_abs]
    for n in names:
        files.append(os.path.join(root, n))


def read(p):
    try:
        if os.path.getsize(p) > 400000:
            return ""
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


# instruction and report files
ag, cl = os.path.join(repo, "AGENTS.md"), os.path.join(repo, "CLAUDE.md")
if not os.path.exists(ag):
    lead("ST-INSTR-1", "AGENTS.md is missing", "AGENTS.md")
if not os.path.exists(cl):
    lead("ST-INSTR-1", "CLAUDE.md is missing", "CLAUDE.md")
elif read(cl).strip() != "@AGENTS.md":
    lead("ST-INSTR-1", "CLAUDE.md is not the single line @AGENTS.md (%d lines)" % len(read(cl).strip().splitlines()), "CLAUDE.md")
for n in ("STATUS.md", "DECISIONS.md", "ASSUMPTIONS.md"):
    if not os.path.exists(os.path.join(repo, n)):
        lead("ST-REPORT-1", n + " is missing", n)

# layout for the parts that should exist by this target
for ph, parts in LAYOUT:
    if order.index(ph) <= pos:
        for part in parts:
            if not os.path.exists(os.path.join(repo, part)):
                lead("ST-LAYOUT-1", "expected by %s but missing: %s" % (ph, part), part)

# GitHub passive, no VMs, no Kubernetes
overrides = owner_overrides(repo)
c1_overrides = sorted(k for k, v in overrides.items() if "C-1" in v)
info["owner_overrides"] = sorted(overrides)
for f in files:
    r = rel(f)
    if "/.github/workflows/" in "/" + r:
        lead("ST-C1", "GitHub Actions workflow present" +
             (" (owner decisions mentioning C-1: %s; confirm one covers this file)" % ", ".join(c1_overrides)
              if c1_overrides else ""), r)
    b = os.path.basename(f).lower()
    if b == "vagrantfile" or b.endswith(".lima.yaml") or b in ("kustomization.yaml", "chart.yaml"):
        lead("ST-C3", "VM or Kubernetes config present", r)

# compose
compose = next((os.path.join(repo, n) for n in ("compose.yaml", "compose.yml", "docker-compose.yml") if os.path.exists(os.path.join(repo, n))), None)
if compose:
    try:
        import yaml
        doc = yaml.safe_load(read(compose)) or {}
    except ImportError:
        doc = None
        info["compose"] = "PyYAML not installed; read compose.yaml by hand or use `docker compose config --format json`"
    except Exception as e:  # noqa
        doc = None
        lead("P0-2", "compose file does not parse: %s" % e, rel(compose))
    if doc is not None:
        nets = doc.get("networks") or {}
        for n in ("prod", "agent", "staging", "ops"):
            if n not in nets:
                lead("ST-NET-1", "network %s is not defined" % n, rel(compose))
            elif not (nets[n] or {}).get("internal"):
                lead("ST-NET-1", "network %s is not internal" % n, rel(compose))
        svcs = doc.get("services") or {}
        info["services"] = sorted(svcs)
        for name, s in svcs.items():
            s = s or {}
            sn = s.get("networks") or []
            sn = list(sn) if not isinstance(sn, dict) else list(sn.keys())
            if "prod" in sn and "agent" in sn:
                lead("ST-NET-1", "service %s joins both agent and prod" % name, rel(compose))
            if "prod" in sn and name in ("launcher", "archon", "board", "egress-proxy", "socket-proxy"):
                lead("ST-NET-1", "agent-side service %s joins prod" % name, rel(compose))
            if s.get("ports") and name not in ("proxy", "reverse-proxy"):
                lead("ST-NET-1", "service %s publishes a host port" % name, rel(compose))
            if s.get("privileged"):
                lead("HR-3", "service %s runs privileged" % name, rel(compose))
            vols = " ".join(map(str, s.get("volumes") or []))
            if "docker.sock" in vols and name != "socket-proxy":
                lead("HR-3", "service %s mounts the Docker socket directly" % name, rel(compose))
            if any(e in name.lower() for e in EARLY_SERVICES):
                lead("ST-EARLY-1", "Pass 2 service in compose: %s" % name, rel(compose))
            if "vllm" in name.lower():
                lead("ST-C3", "vllm-mlx appears as a container: %s" % name, rel(compose))
else:
    lead("P0-2", "no compose file found", "")

# early hardening by path and by word
for p in EARLY_PATHS:
    if os.path.exists(os.path.join(repo, p)):
        lead("ST-EARLY-1", "Pass 2 path present: %s" % p, p)
full_loop = False
vdir = os.path.join(repo, "verification")
if os.path.isdir(vdir):
    for n in os.listdir(vdir):
        vj = os.path.join(vdir, n, "verdict.json")
        if os.path.exists(vj):
            try:
                v = json.load(open(vj))
                if v.get("target") == "full-loop" and v.get("verdict") == "VERIFIED":
                    full_loop = True
            except Exception:  # noqa
                pass
info["full_loop_verified_report"] = full_loop

for f in files:
    r = rel(f)
    if not is_text(f):
        continue
    t = read(f)
    if not t:
        continue
    for i, line in enumerate(t.splitlines(), 1):
        for label, rx in SECRET_RX:
            if re.search(rx, line):
                lead("ST-SEC-1", "%s-shaped string" % label, "%s:%d" % (r, i))
        if INJECT_RX.search(line):
            lead("ST-INJECT-1", "text that may be addressed to a verifier: %s" % line.strip()[:120], "%s:%d" % (r, i))
        if not r.endswith(".md"):
            for label, rx in EARLY_WORDS:
                if re.search(rx, line, re.I):
                    lead("ST-EARLY-1", "Pass 2 marker (%s)" % label, "%s:%d" % (r, i))

# tracked .env files
try:
    out = subprocess.run(["git", "-C", repo, "ls-files"], capture_output=True, text=True, timeout=20)
    if out.returncode == 0:
        for n in out.stdout.splitlines():
            if os.path.basename(n) == ".env" or n.endswith(".env"):
                lead("ST-SEC-1", "tracked .env file", n)
    else:
        info["git"] = "not a git repo or git failed; ST-SPEC-2 and tracked-file checks need git"
except Exception:  # noqa
    info["git"] = "git not available"

# who changed the specs (ST-SPEC-2)
try:
    out = subprocess.run(["git", "-C", repo, "log", "--format=%h|%an|%s", "--", a.spec_dir],
                         capture_output=True, text=True, timeout=20)
    commits = [l.split("|", 2) for l in out.stdout.splitlines() if l.count("|") >= 2]
    info["spec_commits"] = [{"commit": c[0], "author": c[1], "subject": c[2]} for c in commits]
    if len(commits) > 1:
        for c in commits[:-1]:
            lead("ST-SPEC-2", "spec directory changed after it was first added: %s by %s (%s)" % (c[0], c[1], c[2]), a.spec_dir)
    dirty = subprocess.run(["git", "-C", repo, "status", "--short", "--", a.spec_dir, "verification"],
                           capture_output=True, text=True, timeout=20).stdout.rstrip()
    for l in dirty.splitlines():
        path = l[3:].strip()
        if path.startswith(a.spec_dir) or not l.startswith("??"):
            lead("ST-SPEC-2", "uncommitted change to a spec or to an existing verification report: %s" % l.strip(), path)
except Exception:  # noqa
    pass

# numeric defaults repeated in code (ST-SEAM-3)
dflt = read(os.path.join(repo, "config", "defaults.yaml"))
nums = sorted(set(re.findall(r":\s*(\d{2,})\b", dflt)), key=int) if dflt else []
if nums:
    rxn = re.compile(r"(?<![\w.])(%s)(?![\w.])" % "|".join(nums))
    for f in files:
        r = rel(f)
        if f.endswith((".py", ".ts", ".js", ".sh")) and not r.startswith(("tests", "config")):
            for i, line in enumerate(read(f).splitlines(), 1):
                if rxn.search(line) and "=" in line and not line.strip().startswith("#"):
                    lead("ST-SEAM-3", "a value from config/defaults.yaml appears as a literal: %s" % line.strip()[:80], "%s:%d" % (r, i))

# which earlier targets have a VERIFIED report (ST-ORDER-1)
verified = set()
if os.path.isdir(vdir):
    for n in os.listdir(vdir):
        vj = os.path.join(vdir, n, "verdict.json")
        if os.path.exists(vj):
            try:
                v = json.load(open(vj))
                if v.get("verdict") == "VERIFIED":
                    verified.add(v.get("target"))
            except Exception:  # noqa
                pass
info["verified_targets"] = sorted(verified)
for t_ in order[:pos]:
    if t_ not in verified:
        lead("ST-ORDER-1", "no VERIFIED report for the earlier target %s" % t_, "verification/")
        break

# agent adapter entries
adir = os.path.join(repo, "launcher", "agents")
if order.index("phase-1") <= pos and os.path.isdir(adir):
    names = " ".join(os.listdir(adir)).lower()
    info["agent_adapters"] = sorted(os.listdir(adir))
    for cli in ("claude", "codex"):
        if cli not in names:
            lead("ST-SEAM-1", "no adapter entry whose name contains %r" % cli, "launcher/agents")

print(json.dumps({"target": target, "leads": leads, "info": info,
                  "reminder": "Leads are places to look. Confirm each by opening it; a clean scan proves nothing by itself."}, indent=1))
