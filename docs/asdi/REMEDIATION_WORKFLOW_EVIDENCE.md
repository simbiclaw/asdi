# Remediation and specification-escalation workflow evidence

**Date:** 2026-11-17  
**Result:** **Implemented and locally verified; independent conformance audit pending**

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

This slice still requires an independent `asdi-build-conformance` audit against its exact candidate revision before acceptance.
