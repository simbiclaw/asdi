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

## Update — 2026-11-17

Added the user-directed verification remediation and specification-escalation control plane. It durably distinguishes the initial audit, two fresh remediation cycles, immediate specification-defect holds, builder specification mutation, persistent failure, owner decisions and hold release. Local controller/CLI tests pass; the slice remains pending independent conformance audit.

## Independent audit response — 2026-11-17

The initial audit failed candidate `df21e4e` without consuming a remediation cycle. Cycle 1 repairs the cited verifier base-volume/verify execution path, evidence provenance, external usage guardrails, CLI override validation, remediation ceiling, specification mutation boundary and subprocess timeout. Focused and full suites pass. A fresh independent audit is required before acceptance.

## Update — live coding-CLI egress transport

Added a live Claude Code proxy adapter, durable proxy-log capture, and a reproducible verifier fixture. The live isolated run exercised Git, npm and local-model traffic through the per-run allowlist proxy. The base verifier independently checked the generated probe and its negative control; the Stop hook recorded completion and absent credential-like environment names. Evidence manifest `m-14f6e99b3711391703429abc` remained valid after teardown. This closes the former Phase 1 live-transport gap, not Phase 1 acceptance.

## Update — builder hardening, 2026-11-17

* Run lifecycle now persists the launcher PID, container, proxy, network and all named volumes; failed and guardrail-killed runs receive terminal durable status; successful and failed runs clean all resources.
* `launcher kill` now uses the persisted identity to stop the launcher/container/proxy and remove the complete per-run resource set.
* Static checks retain their blocking flag; only blocking checks authorize green, while crash/timeout remains `error`.
* Evidence verification is stronger: exact schema/result shape, statement/result check agreement, revision-bound subject, allowed/safe object paths, exact object inventory, hash and size checks, feature evidence references, producer image, environment/tool versions and input bindings.
* Egress CONNECT/plain-HTTP forwarding now connects to the address resolved during authorization, preventing DNS re-resolution from changing the validated destination.
* Local verification: `PYTHONPATH=src:. python3 -m unittest discover -s tests -v` ran 100 tests, with 100 passes and four host-sensitive skips. This is changed-slice evidence only; independent conformance and Phase 1 acceptance remain blocked.
