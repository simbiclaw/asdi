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

## Negative evidence completed

* per-run network/container lifecycle;
* agent adapter running inside the container;
* outside-process guardrail kill;
* base-branch harness checkout and overlay;
* live negative tests for a red verifier, weakened proof, and each guardrail limit.

Implemented and verified:

* an agent exit 0 cannot overturn a forced red verifier;
* `_fresh_export` restores base-branch harness content after an agent weakens it;
* turn guardrail kills a hanging isolated agent;
* runtime key/token names are absent.

## Still required for Phase 1 exit

* durable `launcher status`/`kill` surface;
* spend reporting or explicit local-model token/wall-clock-only evidence;
* live Docker negative tests for each guardrail and weakened harness.

## Update

Implemented and verified with Docker:

* one internal per-run network;
* one workspace volume and one evidence volume;
* non-root isolated agent execution;
* clean base export;
* verifier static checks over the named head volume;
* unsigned content-addressed evidence statement;
* evidence hash verification after teardown;
* turn guardrail kill with a hanging agent.

Negative evidence completed: red verifier, weakened harness proof, spend limit, turn guardrail, and explicit key/token absence.

Durable operations added: `run`, `status`, `list`, and `kill`.
