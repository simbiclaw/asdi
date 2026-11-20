# REV K conformance audit — current worktree

**Scope:** uncommitted `revk/pass1` worktree after `52d4cdc`; Pass 1 / Phase 1 with Phase 4 control-plane slices and PR #2 remediation.
**Result:** **builder-side audit PASS for the changed scope; phase acceptance BLOCKED by owner decisions and missing live re-verification.**

## Source register

All four authoritative files were read locally and their SHA-256 values match `reference/AUTHORITY.md`:

- Design REV K: `5b7c65a64a15a8e1784260178669901d3a5797eefdbd3e40d6f746a24c3bbe1e`
- Stack REV K: `0ad0db6308aab98de941c269dda5065b7158617fb65e4ca9b5d3c2fa1924bef7`
- Build Guide V4 REV K: `c528326ee0a5cb6cb86f061abd747896117a308822b399d7bc471fab13057ee6`
- Trust Handbook REV K: `c368904d42b54cb4df4a3c0a3c2db7b2ee30a4fc774c06383f7d5d155f95b3cd`

## Invariants

| Area | Status | Evidence / boundary |
|---|---|---|
| C-0 board choice deferred behind adapter | PASS | No board implementation or D-9 resolution in the changed paths. |
| C-1 local loops, passive GitHub | PASS | `events/` uses a local journal and bounded read-only `gh` commands; no webhook receiver or Actions were added. |
| C-2 single host | PASS | No second host or cloud dependency was added. |
| C-3 Docker/network isolation | PASS for changed scope | Run setup/cleanup boundary was repaired in `launcher/runner.py`; live Docker re-run remains outstanding after this change. |
| C-4 Archon boundary | NOT_APPLICABLE | No Archon or workflow-pipeline change in this slice. |
| C-5 ASDI-run verification authoritative | PASS | CI derives from integrity-bound static checks; agent-declared `pass` cannot promote a failed or stale result. |
| Seven hard rules | PASS for changed scope | Merge/deploy remain dry-run and human-gated; run sandbox, secrets, guardrails, protected-path checks and verifier override behavior were not weakened. |
| Pass ordering | PASS | No Pass 2 capability was started; Phase 7 release-readiness is governance-only and performs no deployment. |

## Findings and remediation

### P1 — `result.json` run IDs violated the Phase 0 schema — fixed

`EvidenceStore._validate_result` accepted any non-empty `run_id`, while `schemas/result.schema.json` constrained it to `^r-...$`. Verifier-command fixtures used `rv-*`, and verifier-only revision runs generated `rv-*`.

Remediation: the validator now enforces the schema grammar; verifier-only run IDs use `r-v<hex>`; command fixtures use `r-vcommand` / `r-vmaincommand`; the schema pattern was corrected to allow the hyphenated IDs already used by valid runs. Regression: `tests.test_revk_phase1.EvidenceStoreTests.test_invalid_run_id_is_rejected`.

### PR #2 remediation — fixed

- F-1 setup failure now cleans resources and records terminal failure.
- F-2 plain HTTP egress connects only to authorization-validated addresses.
- F-3 Claude adapter rejects credential-like environment names.
- F-4 was dispositioned in `docs/asdi/PR2_REVIEW_RESPONSE.md`.

## Verification

```sh
PYTHONPATH=.:src python3 -m unittest discover -s tests -v
```

Observed: **200 tests, OK, 4 expected sandbox skips**. `git diff --check` is clean.

## Boundaries

This is builder-side evidence, not ASDI acceptance. No phase exit, live Docker re-verification, independent auditor verdict, GitHub post, merge, deployment or exposure occurred. Phase 3 still needs an owner-selected pilot; Phase 1 acceptance still needs an owner-selected independent auditor command.
