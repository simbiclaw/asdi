# Remediation and specification-escalation workflow evidence

**Date:** 2026-11-17  
**Result:** **Initial audit failed; remediation cycle 1 implemented and locally verified**

## Implemented behavior

- [`launcher/remediation.py`](../../launcher/remediation.py) persists workflow state, candidate revisions, verifier findings, remediation cycles, specification hashes, hold state, feedback reports and owner decisions.
- [`launcher/remediation_cli.py`](../../launcher/remediation_cli.py) exposes `audit`, `remediate`, `status`, `report` and `owner-decision`.
- The initial audit is separate from remediation accounting.
- A failed implementation audit may run no more than two builder cycles.
- Every cycle writes a separate verification report and records its exact candidate revision.
- The controller reports a stale worktree as a distinct candidate using `<commit>+worktree:<tree-id>`.
- A verifier can trigger immediate specification escalation through `spec_feedback.required`, top-level `spec_defect`, a `SPEC_*` blocked reason, or a finding marked `spec_defect`/`spec_conflict`.
- Builder edits to configured authoritative specification paths trigger immediate escalation and are preserved in cycle evidence.
- Two failed remediation cycles trigger persistent-failure escalation.
- Escalation writes a durable Specification Feedback Report and blocks further affected controller work until an explicit owner decision is recorded.

## Local execution evidence

Focused suite:

```sh
PYTHONPATH=src:. python3 -m unittest tests.test_remediation_controller -v
```

Observed result:

```text
Ran 7 tests in 2.589s
OK
```

The tests cover:

- initial-pass acceptance with zero remediation cycles;
- one fresh candidate plus fresh verifier invocation;
- persistent failure after exactly two cycles;
- immediate specification-defect hold;
- immediate specification-mutation hold;
- explicit owner decision and hold release;
- CLI audit plus durable status retrieval.

## Verification and escalation boundary

The controller mechanically enforces report parsing, pass predicates, two-cycle accounting, candidate identity, durable escalation and owner-decision recording. It does not itself construct the container boundary. Builder and verifier commands must be wrapped by the ASDI launcher/container path when used for enforcement-class work; the current direct subprocess support is a local workflow control-plane implementation and must not be described as run-sandbox evidence.

## Independent initial audit

- Candidate: `df21e4e`
- Verifier: independent `asdi-build-conformance` agent
- Result: `FAIL`
- Remediation cycles consumed by the initial audit: `0`

Primary implementation findings repaired in cycle 1:

1. The remediation CLI could override the ceiling above two cycles.
2. Specification mutation detection was post-hoc only and could miss a transient edit.
3. Builder/verifier timeouts were caught but never supplied to `subprocess.run`.
4. The verifier referenced a base volume that was never populated and did not run the base-branch verify entrypoint.
5. Evidence identity collided across runs and lacked producer/environment/input metadata.
6. Turn guardrail counted polling iterations rather than structured runtime turns, spend/token events were not enforced externally, and CLI guardrail overrides were discarded.

The audit also reported `SPEC_SYNC_CONFLICT` for Design REV K versus the Handbook/Build Guide metadata. That issue is governed by [`docs/asdi/SPEC_FEEDBACK_HANDBOOK_SYNC.md`](SPEC_FEEDBACK_HANDBOOK_SYNC.md), not by implementation remediation.

## Remediation cycle 1

Implemented:

- hard remediation ceiling of two cycles in the controller and CLI;
- read-only specification protection plus content/mode mutation escalation;
- configured builder/verifier subprocess timeouts;
- populated base volume and execution of base `verify/bin/verify` after static gates;
- unique content-addressed evidence identity with verifier/run image, base harness, gate-manifest and product-profile bindings;
- structured `turn` and `usage` events, external token/spend/turn enforcement, and persisted usage evidence;
- validated launcher CLI override contract and explicit local-agent cost.

Focused execution:

```sh
PYTHONPATH=src:. python3 -m unittest tests.test_remediation_controller tests.test_revk_phase1 tests.test_revk_runner tests.test_revk_verifier_authority tests.test_revk_guardrails tests.test_launcher_cli
```

Observed:

```text
Ran 20 tests in 3.389s
OK
```

Full execution:

```sh
PYTHONPATH=.:src python3 -m unittest discover -s tests -v
```

Observed:

```text
Ran 89 tests in 10.735s
OK (skipped=3)
```

The three skips are the existing expected AF_UNIX sandbox limitations, not new failures. A fresh independent verifier must audit the cycle-1 commit. Actual Docker execution of the repaired verifier path remains outstanding until that audit or a subsequent execution run provides host evidence.

## Live verifier-mount correction (2026-11-17)

A live Phase 1 fixture run failed closed with a valid red evidence statement. Investigation showed that the trusted base volume was populated and visible before verification, but the verifier command mounted it with:

```text
--mount type=volume,source=asdi-base-...,destination=/opt/base:ro
```

Docker 29.6.1 interpreted the `:ro` suffix as part of the `--mount` destination, so `/opt/base/verify/bin/verify` did not exist. Both base mounts now use:

```text
--mount type=volume,source=asdi-base-...,destination=/opt/base,readonly
```

A regression test records Docker arguments through a fake CLI and rejects the invalid `destination=/opt/base:ro` form. After the correction, a fresh live fixture run returned `status=succeeded`; `static:compile` and `verify:base-harness` both returned `pass`; evidence manifest `m-095e4dff7674109d1db08001` validated against fixture commit `726950b7ea027f0914b59d7b97b12bb37544cc9c`; runtime evidence recorded `socket_mounted=false` and `secrets_mounted=false`.

The independent specification hold remains active. This correction is implementation evidence only and does not authorize a synchronized four-document acceptance claim.
