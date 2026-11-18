#!/usr/bin/env python3
"""PR gate profile: decide every mechanically decidable row for one PR, fast.

  pr_check.py --repo . --base <sha> --head <sha> --out DIR [--phase phase-1]
              [--test-cmd "python3 -m unittest discover -s tests -v"] [--skip-tests]

Writes DIR/results.json for target "pr" and DIR/evidence/*. Rows it can decide with
evidence (and a control where the row has one) are filled in. Rows that need
judgment are left with status "" and "needs_confirmation": true plus the leads to
open; report.py refuses a verdict until the verifier has settled them.

The rule for the PR profile: a standing row fails only for a problem present at the
PR head and absent at the base. Problems already on the base go in notes as
pre-existing, so old debt is visible without blocking every PR.

Safety (references/method.md): the PR is never checked out in the working tree. Base
and head are exported with `git archive` into scratch directories; the builder's
tests run there with an empty environment and, where `unshare` works, no network.
"""
import sys, os
sys.dont_write_bytecode = True  # keep the skill folder unchanged
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import argparse, datetime, fnmatch, json, re, shutil, subprocess, tempfile, time
from common import authority, git, load_register, owner_overrides, select, sha256

HERE = os.path.dirname(os.path.abspath(__file__))
SECRET_RX = [("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{20,}"), ("GitHub fine-grained token", r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
             ("Anthropic key", r"\bsk-ant-[A-Za-z0-9_-]{16,}"), ("API key", r"\bsk-[A-Za-z0-9]{24,}"),
             ("AWS key id", r"\bAKIA[0-9A-Z]{16}\b"), ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]
INJECT_RX = re.compile(r"(?i)\b(verifier|reviewer|auditor)s?\b[^.\n]{0,80}\b(mark|record|treat|skip|ignore|approve|assume|do not (check|run|verify))\b"
                       r"|\b(mark|record|treat)\b[^.\n]{0,40}\bas (pass|passed|verified|green)\b")
GENERATED = ["vendor/*", "third_party/*", "dist/*", "build/*", "*/generated/*", "generated/*", "*.generated.*"]
VERIFICATION = ["verify/*", "evals/*", ".asdi/*"]
FLAGGED = ["tests/*", "ci/*", ".github/*"]
ORCHESTRATION = ["compose.yaml", "compose.yml", "docker-compose.yml", "archon/*", "board/*", "launcher/*", "events/*"]
CLAIM_RX = re.compile(r"(?i)(\|\s*pass\s*\||\[x\]|\b(passed|passes|complete[d]?|verified|done|accepted)\b)")
TEST_LINE = re.compile(r"^(test\S*) \((\S+)\)(?: \.\.\.| \S.*\.\.\.)?\s*(ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$")
CONTROL_TEST = '''import unittest


class AsdiVerifyControl(unittest.TestCase):
    def test_control_must_fail(self):
        self.assertEqual(1, 2, "planted by asdi-build-verify as a control")
'''


def match(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def export(repo, sha, dest):
    os.makedirs(dest, exist_ok=True)
    archive = subprocess.run(["git", "-C", repo, "archive", sha], capture_output=True, timeout=300)
    if archive.returncode != 0:
        raise SystemExit("git archive %s failed: %s" % (sha, archive.stderr.decode()[:300]))
    subprocess.run(["tar", "-x", "-C", dest], input=archive.stdout, check=True)


def sandboxed(cmd, cwd, timeout):
    """Run builder code with an empty environment and, if possible, no network."""
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": cwd, "PYTHONPATH": ".:src", "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1"}
    prefix = []
    if shutil.which("unshare") and subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode == 0:
        prefix = ["unshare", "-rn"]
    start = time.time()
    try:
        p = subprocess.run(prefix + ["sh", "-c", cmd], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr, time.time() - start, bool(prefix)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return None, out, time.time() - start, bool(prefix)


def test_outcomes(log):
    """{test id: outcome} from unittest -v output (handles subTest-free and subTest lines)."""
    out = {}
    for line in log.splitlines():
        m = TEST_LINE.match(line.strip())
        if m:
            out["%s.%s" % (m.group(2), m.group(1)) if not m.group(2).endswith(m.group(1)) else m.group(2)] = m.group(3).split()[0]
    for m in re.finditer(r"^(FAIL|ERROR): (\S+) \((\S+)\)", log, re.M):
        tid = m.group(3) if m.group(3).endswith(m.group(2)) else "%s.%s" % (m.group(3), m.group(2))
        out.setdefault(tid, m.group(1))
    return out


def added_lines(repo, base, head):
    """[(path, new line number, text)] for lines the PR adds."""
    diff = git(repo, "diff", "-U0", "--no-color", base, head, timeout=120).stdout
    out, path, n = [], None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.match(r"@@ -\S+ \+(\d+)", line)
            n = int(m.group(1)) if m else 0
        elif line.startswith("+") and path:
            out.append((path, n, line[1:]))
            n += 1
    return out


def scan(repo_dir, phase):
    p = subprocess.run([sys.executable, os.path.join(HERE, "repo_scan.py"), "--repo", repo_dir, "--target", phase],
                       capture_output=True, text=True, timeout=300)
    return json.loads(p.stdout)["leads"]


def lead_key(l):
    return (l["row"], re.sub(r":\d+$", "", l["where"]), re.sub(r"\d+ lines", "N lines", l["detail"]))


def phase_of(repo_dir):
    try:
        text = open(os.path.join(repo_dir, "STATUS.md"), encoding="utf-8").read()
    except OSError:
        return "phase-0"
    m = re.search(r"Current phase:\**\s*Phase\s+(\d+)", text, re.I)
    return "phase-%s" % m.group(1) if m else "phase-0"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", required=True, help="the PR's base commit (or merge base)")
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--phase")
    ap.add_argument("--test-cmd", default="python3 -m unittest discover -s tests -v")
    ap.add_argument("--test-timeout", type=int, default=900)
    ap.add_argument("--skip-tests", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    repo = os.path.abspath(a.repo)
    base = git(repo, "merge-base", a.base, a.head).stdout.strip() or a.base
    head = git(repo, "rev-parse", a.head).stdout.strip()
    if not head:
        raise SystemExit("unknown head commit %s (fetch it first)" % a.head)
    out = os.path.abspath(a.out)
    ev = os.path.join(out, "evidence")
    os.makedirs(ev, exist_ok=True)
    if os.path.exists(os.path.join(out, "results.json")):
        raise SystemExit("%s/results.json already exists; refusing to overwrite a verification record" % out)
    scratch = tempfile.mkdtemp(prefix="asdi-pr-verify-")
    bdir, hdir = os.path.join(scratch, "base"), os.path.join(scratch, "head")
    export(repo, base, bdir)
    export(repo, head, hdir)
    phase = a.phase or phase_of(bdir)
    reg = load_register()
    rows = select(reg, "pr", phase)
    res = {r["id"]: {"id": r["id"], "status": "", "control": "", "observed": "", "evidence": [], "limits": []} for r in rows}
    notes = []

    def save(name, text):
        open(os.path.join(ev, name), "w", encoding="utf-8").write(text)
        return "evidence/" + name

    def settle(rid, status, observed, evidence=(), control="", limits=()):
        if rid in res:
            res[rid].update(status=status, observed=observed, evidence=list(evidence), control=control,
                            limits=list(limits), prefilled_by="pr_check.py")

    def ask(rid, observed, leads):
        if rid in res:
            res[rid].update(observed=observed, needs_confirmation=True, leads=leads, prefilled_by="pr_check.py")

    status = git(repo, "diff", "--name-status", "-M", base, head).stdout.splitlines()
    changes = [(l.split("\t")[0][0], l.split("\t")[-1]) for l in status if "\t" in l]
    paths = [p for _, p in changes]
    diff_ev = save("diff-name-status.txt", "\n".join(status) + "\n")
    adds = added_lines(repo, base, head)

    # PR-PROT-1: generated/vendored edits; verification files mixed with other paths
    gen = [p for p in paths if match(p, GENERATED)]
    ver_edits = [p for k, p in changes if match(p, VERIFICATION) and k in "MDR"]
    others = [p for p in paths if not match(p, VERIFICATION)]
    flagged = [p for p in paths if match(p, FLAGGED)]
    if gen:
        settle("PR-PROT-1", "fail", "The PR edits generated or vendored paths: %s" % ", ".join(gen), [diff_ev])
    elif ver_edits and others:
        settle("PR-PROT-1", "fail", "Split the PR: it edits existing verification files (%s) together with other paths (%s)"
               % (", ".join(ver_edits), ", ".join(others[:5])), [diff_ev])
    else:
        settle("PR-PROT-1", "pass", "No generated or vendored path is edited and no existing verification file is "
               "mixed with other changes (%d paths changed)." % len(paths), [diff_ev],
               limits=["Path rules from Guide §9.1/§9.3 only; class routing is the gate's class check."])
    if flagged:
        notes.append("Flagged for review (tests, CI or workflow changes): " + ", ".join(flagged))

    # ST-SPEC-1 with pins at the head, plus a control
    pins = authority(hdir)
    if pins and len(pins["specs"]) == 4:
        bad = [s["path"] for s in pins["specs"]
               if not os.path.exists(os.path.join(hdir, s["path"])) or sha256(os.path.join(hdir, s["path"])) != s["sha256"]]
        probe = os.path.join(scratch, "control-spec")
        shutil.copy(os.path.join(hdir, pins["specs"][0]["path"]), probe)
        with open(probe, "ab") as f:
            f.write(b"\n<!-- control -->\n")
        control = "caught" if sha256(probe) != pins["specs"][0]["sha256"] else "missed"
        lines = ["%s %s" % (s["sha256"], s["path"]) for s in pins["specs"]]
        e = save("spec-pins.txt", "pinned (AUTHORITY.md at head):\n" + "\n".join(lines) + "\nmismatched: %s\n" % bad)
        if bad or control != "caught":
            settle("ST-SPEC-1", "fail", "Pinned specs missing or not matching their pins: %s" % (bad or "control missed"),
                   [e], control)
        else:
            settle("ST-SPEC-1", "pass", "All four specs pinned in reference/AUTHORITY.md exist at the head and match "
                   "their SHA-256 pins.", [e, "reference/AUTHORITY.md"], control)
    else:
        ask("ST-SPEC-1", "No AUTHORITY.md pins at the head; run spec_set.py on the head copy and judge.", [])

    # ST-SPEC-2: the PR must not touch specs, the authority file, this skill or reports
    protected = {s["path"] for s in (authority(bdir) or {"specs": []})["specs"]} | {"reference/AUTHORITY.md"}
    touched = [p for p in paths if p in protected or p.startswith(("skills/asdi-build-verify/", "verification/"))]
    decisions = owner_overrides(bdir)
    if touched:
        settle("ST-SPEC-2", "fail", "The PR changes protected verification inputs: %s. This needs owner work; "
               "cite an owner decision from the base DECISIONS.md as override if one covers it." % ", ".join(touched),
               [diff_ev])
    else:
        settle("ST-SPEC-2", "pass", "The diff touches no spec, AUTHORITY.md, verify-skill or verification/ path.", [diff_ev],
               limits=["Earlier history of the specs is a phase-verification question (git log), not a PR one."])

    # ST-INSTR-1 and ST-REPORT-1 at the head
    claude = os.path.join(hdir, "CLAUDE.md")
    ok = os.path.exists(os.path.join(hdir, "AGENTS.md")) and os.path.exists(claude) and \
        open(claude, encoding="utf-8").read().strip() == "@AGENTS.md"
    settle("ST-INSTR-1", "pass" if ok else "fail",
           "AGENTS.md exists and CLAUDE.md is exactly @AGENTS.md at the head." if ok else
           "At the head, AGENTS.md is missing or CLAUDE.md is not exactly @AGENTS.md.", ["CLAUDE.md", "AGENTS.md"])
    missing = [n for n in ("STATUS.md", "DECISIONS.md", "ASSUMPTIONS.md") if not os.path.exists(os.path.join(hdir, n))]
    settle("ST-REPORT-1", "fail" if missing else "pass",
           ("Missing at the head: %s" % ", ".join(missing)) if missing else
           "STATUS.md, DECISIONS.md and ASSUMPTIONS.md exist at the head.", ["STATUS.md"])

    # ST-SEC-1 on added lines, with a planted control
    def secrets(lines):
        return [(p, n, label) for p, n, text in lines for label, rx in SECRET_RX if re.search(rx, text)]
    hits = secrets(adds) + [(p, 0, "tracked .env file") for k, p in changes if k != "D" and
                            (os.path.basename(p) == ".env" or p.endswith(".env"))]
    control = "caught" if secrets([("control", 1, "token = ghp_" + "A1b2C3d4E5" * 4)]) else "missed"
    e = save("secret-scan.txt", "\n".join("%s:%d %s" % h for h in hits) or "no token-shaped string in added lines\n")
    if hits:
        settle("ST-SEC-1", "fail", "Token-shaped strings in added lines (values not printed): " +
               ", ".join("%s:%d (%s)" % h for h in hits[:10]), [e], control)
    else:
        settle("ST-SEC-1", "pass" if control == "caught" else "fail",
               "No token-shaped string or .env file in the %d lines the PR adds." % len(adds), [e], control,
               ["Shape matching only; a secret in an unknown format is not detected."])

    # ST-INJECT-1 on added lines
    inj = [(p, n, text.strip()[:160]) for p, n, text in adds if INJECT_RX.search(text)]
    if inj:
        ask("ST-INJECT-1", "Added lines that may address a verifier or reviewer; open each and confirm.",
            ["%s:%d %s" % i for i in inj])
    else:
        settle("ST-INJECT-1", "pass", "No added line addresses a verifier or reviewer.", [diff_ev],
               limits=["Pattern scan of added lines; the reviewer still reads the diff as data."])

    # Lead-diff rows: new leads at the head versus the base
    base_leads, head_leads = scan(bdir, phase), scan(hdir, phase)
    bkeys = {lead_key(l) for l in base_leads}
    new = [l for l in head_leads if lead_key(l) not in bkeys]
    e = save("scan-leads.json", json.dumps({"base": base_leads, "head": head_leads, "new_at_head": new}, indent=1))
    for rid in ("ST-LAYOUT-1", "ST-EARLY-1", "ST-C1", "ST-C3", "ST-NET-1", "ST-SEAM-3", "ST-SEAM-1"):
        mine = [l for l in new if l["row"] == rid]
        pre = [l for l in base_leads if l["row"] == rid]
        if pre:
            notes.append("%s: %d lead(s) pre-existing at the base, not introduced by this PR." % (rid, len(pre)))
        if mine:
            ask(rid, "Leads introduced by this PR; open each and confirm.",
                ["%s: %s" % (l["where"], l["detail"]) for l in mine])
        else:
            settle(rid, "pass", "repo_scan.py finds no %s lead at the head that is absent at the base (%d pre-existing)."
                   % (rid, len(pre)), [e], limits=["Static leads only; the reviewer reads the diff itself."])

    # ST-C1 also covers changes to an existing workflow, which a lead diff cannot see
    wf = [p for p in paths if p.startswith(".github/workflows/")]
    if wf and "ST-C1" in res:
        cover = sorted(k for k, v in decisions.items() if "C-1" in v)
        ask("ST-C1", "The PR adds or changes GitHub workflows. This is a fail unless an owner decision in the base "
            "DECISIONS.md covers it (record that ID as override). Owner decisions mentioning C-1 at the base: %s"
            % (", ".join(cover) or "none"), wf + res["ST-C1"].get("leads", []))
        res["ST-C1"]["status"] = ""

    # Diff-reading rows: decide trivially when the diff cannot touch them
    touches = [p for p in paths if match(p, ORCHESTRATION)]
    for rid in ("ST-C0", "ST-C4", "ST-SEAM-2"):
        if touches:
            ask(rid, "The diff touches orchestration surfaces; open them and judge.", touches)
        else:
            settle(rid, "pass", "The diff touches no orchestration surface (compose, archon/, board/, launcher/, events/).",
                   [diff_ev])
    claims = [(p, n, text.strip()) for p, n, text in adds if p == "STATUS.md" and CLAIM_RX.search(text)]
    if claims:
        ask("ST-CLAIM-1", "Lines added to STATUS.md that claim success; confirm each or mark it unconfirmed in claims.",
            ["STATUS.md:%d %s" % (n, t[:160]) for _, n, t in claims])
    else:
        settle("ST-CLAIM-1", "pass", "The PR adds no success claim to STATUS.md.", [diff_ev])

    # PR-TEST-1: no new failing test, with a planted-failure control
    if a.skip_tests:
        settle("PR-TEST-1", "blocked", "Tests skipped by --skip-tests.")
    else:
        rb, lb, tb, isolated = sandboxed(a.test_cmd, bdir, a.test_timeout)
        rh, lh, th, _ = sandboxed(a.test_cmd, hdir, a.test_timeout)
        eb, eh = save("tests-base.log", lb), save("tests-head.log", lh)
        ob, oh = test_outcomes(lb), test_outcomes(lh)
        os.makedirs(os.path.join(hdir, "tests"), exist_ok=True)
        open(os.path.join(hdir, "tests", "test_zz_asdi_verify_control.py"), "w").write(CONTROL_TEST)
        cmd = a.test_cmd.replace("discover -s tests", "discover -s tests -p test_zz_asdi_verify_control.py")
        _, lc, _, _ = sandboxed(cmd, hdir, 120)
        ec = save("tests-control.log", lc)
        control = "caught" if any(v in ("FAIL", "ERROR") for v in test_outcomes(lc).values()) else "missed"
        bad = lambda o: {t for t, v in o.items() if v in ("FAIL", "ERROR")}
        newly = sorted(t for t in bad(oh) if t in ob and ob[t] not in ("FAIL", "ERROR"))
        new_tests_failing = sorted(t for t in bad(oh) if t not in ob)
        lims = ["Network isolated: %s. Empty environment." % ("yes" if isolated else "no (unshare unavailable)"),
                "Base %.0fs, head %.0fs." % (tb, th)]
        if rh is None:
            settle("PR-TEST-1", "error", "The test run at the head timed out after %ds." % a.test_timeout, [eh], control, lims)
        elif not oh:
            settle("PR-TEST-1", "error", "No test outcome could be parsed from the head run.", [eh], control, lims)
        elif newly or new_tests_failing:
            settle("PR-TEST-1", "fail", "Tests passing at the base fail at the head: %s%s"
                   % (", ".join(newly[:10]) or "none",
                      ("; new tests failing: " + ", ".join(new_tests_failing[:10])) if new_tests_failing else ""),
                   [eb, eh], control, lims)
        else:
            pre = sorted(bad(ob) & bad(oh))
            if pre:
                notes.append("PR-TEST-1: %d test(s) fail at both base and head (pre-existing): %s"
                             % (len(pre), ", ".join(pre[:8])))
            settle("PR-TEST-1", "pass" if control == "caught" else "fail",
                   "%d tests at the head; none that passes at the base fails at the head." % len(oh),
                   [eb, eh, ec], control, lims)
    shutil.rmtree(scratch, ignore_errors=True)

    record = {
        "target": "pr", "phase": phase, "spec_revision": reg["spec"]["revision"],
        "guide_version": reg["spec"]["guide_version"], "repo": repo, "commit": head, "base": base,
        "verifier": {"agent": "", "built_this_target_in_same_session": None},
        "started": datetime.datetime.fromtimestamp(t0, datetime.timezone.utc).isoformat(timespec="seconds"),
        "finished": "", "base_owner_decisions": decisions,
        "results": list(res.values()), "claims": [], "notes": notes,
    }
    json.dump(record, open(os.path.join(out, "results.json"), "w", encoding="utf-8"), indent=1)
    todo = [r["id"] for r in res.values() if r.get("needs_confirmation")]
    print(json.dumps({"out": out, "phase": phase, "base": base, "head": head, "seconds": round(time.time() - t0, 1),
                      "decided": {r["id"]: r["status"] for r in res.values() if r["status"]},
                      "needs_confirmation": todo}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
