# REV K Phase 1 progress

**Date:** 2026-11-16  
**Status:** **In progress — core verifier/evidence primitives implemented**

## Implemented

* `launcher/contract.py` validates the REV K contract schema subset and fails closed on missing `done_check`.
* `launcher/evidence.py` implements the Pass 1 evidence store:
  * content-addressed manifest ID;
  * write-once read-only objects;
  * unsigned in-toto statement;
  * SHA-256 integrity verification;
  * survival after launcher/process exit;
  * tamper detection.
* `launcher/static_gates.py` models the verifier static-gate runner:
  * each declared command runs in a container;
  * no network;
  * capabilities dropped;
  * no-new-privileges;
  * read-only root with writable `/tmp`;
  * timeout maps to `error`, never pass.

## Verification

```sh
PYTHONPATH=src:. python3 -m unittest tests.test_revk_phase1 -v
PYTHONPATH=.:src python3 -m unittest discover -s tests -v
git diff --check
```

The REV K Phase 1 tests prove valid/missing `done_check`, evidence retention, hash validation, and tamper detection.

## Still required for Phase 1 exit

* per-run network/container lifecycle;
* agent adapter running inside the container;
* outside-process guardrail kill;
* base-branch harness checkout and overlay;
* live negative tests for a red verifier, weakened proof, and each guardrail limit.
