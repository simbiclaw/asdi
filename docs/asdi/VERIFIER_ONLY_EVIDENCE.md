# Verifier-only revision evidence

**Date:** 2026-11-19  
**Result:** **Verifier-only orchestration implemented and builder-tested; live Docker PR verification not run**

## Implemented

[`launcher/runner.py`](../../launcher/runner.py) now has `REVKLauncher.verify_revision()` and [launcher/cli.py](../../launcher/cli.py) exposes `launcher verify`. This operation verifies one exact Git revision independently of an agent run:

- resolves the requested revision to a full 40-character Git SHA;
- exports that exact revision as the workspace under test;
- exports the configured base branch as the verification harness;
- creates separate workspace and base volumes;
- runs static checks and the base verifier with `--network none`, dropped capabilities, no-new-privileges, read-only root and bounded tmpfs;
- passes the exact target SHA to the verifier;
- requires a schema-2 result bound to the verifier run and exact commit;
- requires every feature to pass and every negative control to be caught;
- records valid content-addressed evidence through `EvidenceStore`;
- records `network: none`, no socket, no secrets and no agent start;
- tears down the workspace/base volumes on success and failure.

It starts no agent container, proxy, or run network. The result schema is `asdi.verifier-only-result/v1`; source may be `pr-head` or `main`. The CLI output is suitable for `events.cli run-pr-gate --evidence` when its manifest source is `pr-head`.

Operational shape:

```sh
PYTHONPATH=.:src python3 -m launcher.cli \
  --root ./state \
  --product-root <product-repository> \
  --base-branch main \
  verify \
  --revision <full-sha-or-ref> \
  --source pr-head \
  --output ./state/verification.json
```

## Builder-side execution

Focused tests in [`tests/test_revk_runner.py`](../../tests/test_revk_runner.py) prove:

- successful verifier-only orchestration has no started agent, no proxy, no Docker socket mount, no secrets mount and `network: none`;
- evidence is valid, source-bound and persisted under the evidence store;
- workspace/base volumes are removed after success;
- a verifier result with a missed negative control remains red and tears down resources.

Existing verifier-authority tests still prove that the base harness runs on a separate base volume, binds `ASDI_COMMIT`, and rejects agent-weakened results. Full suite at this slice: **177 tests, OK, 4 expected socket/TCP skips**.

## Timeout containment

Static-gate and base-harness verifier containers now have deterministic names. If execution exceeds its configured timeout, ASDI invokes Docker `kill` followed by `rm -f`, records both cleanup commands and exit codes, and still reports `error` so the gate remains red. Cleanup failure cannot convert a timeout into success; it is retained in `timeout_cleanup` for operations. This prevents a hung verifier from outliving the launcher merely because the host-side Docker client process was terminated.

Focused tests prove both paths:

- static check timeout names the container, then executes `docker kill` and `docker rm -f`;
- base-harness timeout names `asdi-verify-<short>`, then executes the same kill/remove sequence.

Full suite after this hardening: **179 tests, OK, 4 expected socket/TCP skips**.

## Explicit verifier-command integration

[`events/verifier_command.py`](../../events/verifier_command.py) connects this verifier-only result to the PR gate pipeline through an explicit command boundary. The command must use an absolute executable, receives `{head}` and `{output}` placeholders, runs shell-free with a timeout and a fixed minimal environment, and rejects credential-like command text. It does not inherit the caller environment.

The adapter validates the exact PR head, result schema, source, checks, EvidenceStore binding, subject binding, feature results and runtime boundary (`network: none`; no socket, secrets or agent). It also rejects a nonzero exit from a claimed-success result and refuses to promote a `failed` verifier status even if embedded evidence appears green. Missing, malformed, stale or timed-out output becomes a durable red verifier with execution provenance.

`events.cli run-pr-gate` now accepts either `--evidence` or an explicit `--verifier` command. In command mode it persists the complete verification execution separately, appends only normalized gate fields to the durable journal, then runs review, packet assembly and the existing T0 merge dry-run. The command remains a prototype integration: it invokes the configured verifier command, but live acceptance still requires a real pilot and independent verification.

Full suite after this integration: **185 tests, OK, 4 expected socket/TCP skips**.

## Exact-main verifier-command integration

The same command adapter now supports `source: main`. [`events/main_pipeline.py`](../../events/main_pipeline.py) and `events.cli run-main-verification` use it to verify the durable exact landed `main` commit. The command is absolute, shell-free, bounded and environment-restricted; its result must bind the manifest subject/result to that exact commit, use `source: main`, and prove the verifier-only runtime boundary.

The pipeline appends normalized `github.main_verification_completed` evidence, dispatches it to the existing durable post-merge workflow, and computes deployment eligibility from only that exact passing result. A missed negative control, failed verifier status, nonzero success exit, malformed result or timeout stays red and records the auto-revert requirement. Existing verification is replayed without invoking the verifier again. The pipeline never deploys.

Main-only pipelines fail closed if they encounter a PR event without a PR workflow: poller state records the failed event and cursor, so the PR event remains pending instead of being skipped. Full suite after exact-main integration and mixed-event preservation: **188 tests, OK, 4 expected socket/TCP skips**.

## Derived CI authority

Verifier-command results now derive `ci` solely from named `static:*` checks rather than accepting a caller label. A successful verifier requires at least one static check, all blocking static checks passing, no static error, and no nonzero exit. A failed blocking static check becomes verifier failure even if embedded feature evidence appears green. Declared and derived CI mismatches are retained as failures, and the durable event records the derived status.

Full suite after CI derivation: **190 tests, OK, 4 expected socket/TCP skips**.

## Status boundary

| Claim | Status |
|---|---|
| Verifier-only orchestration and CLI | Implemented |
| No-agent/no-network boundaries | Builder-tested with isolated runtime fakes |
| Exact-revision evidence binding | Builder-tested |
| Missed-control red path | Builder-tested |
| Live Docker verification of a real PR head | **Not run** |
| Phase 1 acceptance / Phase 4 exit | **Not claimed** |

A live run remains dependent on a pilot product with `.asdi/product.yaml`, `.asdi/static-gates.yaml` and `verify/` proofs. It must be independently reviewed before any acceptance claim.
