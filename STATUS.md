# ASDI REV K implementation status

**Revision set:** REV K  
**Current pass:** Pass 1  
**Current phase:** Phase 0 — scaffold  

## Completed

- [x] Reference set imported under `reference/`.
- [x] Agent-neutral instruction files added.
- [x] REV K zone topology added to `compose.yaml`.
- [x] JSON Schemas added for Phase 0 artifacts.
- [x] Provisional configuration, identities, policy stub, and judgment-path protection added.
- [x] Machine-checked schema/config/merge-policy suite added.

## Exit-test status

| Phase 0 exit test | Status | Evidence |
|---|---|---|
| Schemas validate examples and reject malformed documents | pass | `tests/test_phase0_scaffold.py` |
| `agent` cannot connect to `prod` | pass by topology plus compose policy | `compose.yaml`, topology tests |
| Agent token is refused on merge | pass | `merge/dry_run.py`, merge-policy tests |
| `agent` cannot reach `prod` | pass | `tests/zone_probe.sh`; separate `asdi-agent` and `asdi-prod` Docker networks |

## REV K Phase 1

Contract validation, evidence store, and static-gate runner primitives are implemented and tested. Per-run container orchestration, in-container agent execution, base-branch harness enforcement, and guardrail negative tests are next.

**Update:** per-run network, workspace/evidence volumes, non-root container execution, static verifier, evidence persistence, turn-kill test, red-verifier override test, and base-harness tamper-ignoration test now pass. Phase 1 remains in progress until durable status/kill CLI and all spend/key negatives pass.

## Next

Phase 1: REV K launcher, verifier container, guardrails, evidence store, and one working agent adapter.

## Boundaries

The older prototype under `src/asdi/` remains available for reference but is not the REV K Pass 1 implementation. Do not extend it to satisfy REV K requirements.
