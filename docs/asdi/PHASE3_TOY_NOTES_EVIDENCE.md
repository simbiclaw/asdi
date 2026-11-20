# Phase 3 toy-notes builder-side evidence

**Status:** builder-side implementation evidence only. This is **not phase acceptance**. Only an ASDI-run verifier with caught controls counts; the agent's claim does not.

## Scope

Owner decision `approve_synthetic_toy_notes` is already recorded in `state/owner-decisions.jsonl`. The reversible config seam is exactly:

```yaml
version: 1
active: toy-notes
pilots:
  toy-notes:
    product_root: pilots/toy_notes
    run_image: asdi/toy-notes-run:latest
```

Reversal is an owner decision that changes `active`. No existing tracked file was edited. Product source is limited to `pilots/toy_notes/src/toy_notes/`; every file there is owned by at least one feature path glob.

## Commands and observed output

From `/Users/russell/workspace/ASDI` on `revk/pass1`:

1. `PYTHONPATH=.:src python3 -m unittest discover -s tests -v`

   ```text
   Ran 239 tests in 27.415s
   OK
   ```

   All 16 new `test_toy_notes*` tests passed, including CLI, HTTP, UI flag, defect injection, harness self-test, deliberate breakage of each feature, changed-path mapping, product metadata validation and `result.json` schema validation.

2. `PYTHONPATH=.:src python3 tools/validate_examples.py`

   ```text
   validated 12 REV K examples
   ```

   Exit 0. Feature front matter, product/static-gate/rule/seed/verify metadata and each generated `result.json` were separately validated against their REV K schemas by the new tests.

3. `PYTHONPATH=.:src python3 pilots/toy_notes/verify/self_test.py`

   ```text
   launch: exit=0 {"launch":"started","status":"pass",...}
   doctor: exit=0 {"checks":{"database":true,"feature_map":true,"healthz":true,"process":true,"readyz":true},"status":"pass"}
   drive: exit=0 {"controls":{"cli-notes":"caught"},"features":{"cli-notes":"pass"},"status":"pass",...}
   control: exit=0 {"controls":{"cli-notes":"caught"}}
   cleanup: exit=0 {"status":"pass","stopped":true,...}
   self-test: pass; result validates; evidence preserved at /var/folders/.../asdi-toy-notes-self-test-r-selftest-...
   ```

   Exit 0. The evidence directory still existed after cleanup.

4. Full harness, no subcommand, all three features:

   ```text
   ASDI_EVIDENCE_DIR=/tmp/asdi-toy-verify.1sCdO8 \
     ASDI_RUN_ID=r-manual-1795183635 \
     pilots/toy_notes/verify/bin/verify
   ```

   ```text
   features: {"cli-notes":"pass","http-notes":"pass","ui-note-list":"pass"}
   controls: {"cli-notes":"caught","http-notes":"caught","ui-note-list":"caught"}
   cleanup: {"status":"pass","stopped":true,...}
   ```

   Exit 0. `result.json` contained `schema: 2`, the matching run id, a git commit and non-empty evidence and limits for every feature.

5. Product static commands from `pilots/toy_notes`:

   ```text
   python3 -m compileall -q src verify
   python3 -m py_compile verify/bin/verify
   python3 verify/tools/secret_scan.py
   ```

   ```text
   secret-scan: clean (12 files)
   ```

   Exit 0. No third-party package, network call, secret or production data is used by the product.

## Deliberate-break observations

The new test suite copies the product into a temporary head, changes one source file per feature and re-runs the harness. Observed results:

- `cli-notes`: forcing creates to fail produces `status=fail`, `control=caught`.
- `http-notes`: disabling `GET /notes` produces `status=fail`, `control=caught`.
- `ui-note-list`: forcing the UI route off produces `status=fail`, `control=caught`.
- An unmapped changed source path makes `drive --changed <base>..<head>` exit 2 without authorizing a feature.

## Seeded-defect patch format

The four `.asdi/seeds/*.patch` files originally contained bare `@@` hunk
markers and could not be applied by `patch`. They now contain valid line-numbered
unified-diff hunks. A live check applied all four patches successfully:

- `S-cli-injection`: harness self-test exits 1 with `cli-notes` `status=fail`, `control=caught`.
- `S-compile-error`: `compileall` exits 1 with a syntax error.
- `S-flag-default`: the config loader rejects `production-target`.
- `S-hidden-flag-policy`: patch applies; the expected catch remains human review.

A regression test in `tests/test_toy_notes_harness.py` validates the hunk headers
and dry-runs every seed patch against its source file.

## Limits

- This run used local processes and loopback ports; no containerized ASDI verifier, launcher, static-gate runner or evidence store was exercised.
- The UI proof checks server-rendered HTML, not a browser engine or JavaScript.
- No external service, production endpoint, real user data, secret or third-party dependency is involved.
- Static gates were run directly from the product root, not through the launcher's containerized gate runner.
- This document records builder-side checks only and does not weaken or replace any main repository gate.
