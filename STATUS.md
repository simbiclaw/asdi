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

## Installed project skills

| Skill | Scope | Purpose |
|---|---|---|
| `asdi-build-conformance` | ASDI repository implementation/build slices | Read-only audit against Design REV K, Stack REV K, Build Guide V4 REV K, and Trust Handbook REV K. Not the toy-product H-1 verification skill. |

Installed at [`skills/asdi-build-conformance/SKILL.md`](skills/asdi-build-conformance/SKILL.md) from [`reference/asdi-build-conformance.zip`](reference/asdi-build-conformance.zip). Its project configuration pins the four REV K sources and excludes toy-product verification evidence.

## REV K Phase 1

Contract validation, evidence store, static-gate runner, per-run container orchestration, non-root execution, named head/base/evidence volumes, and durable run/status/kill operations are implemented and tested.

**Update:** per-run network, workspace/evidence volumes, non-root container execution, static verifier, evidence persistence, turn-kill test, red-verifier override test, base-harness tamper-ignoration test, spend preflight, and durable status/kill CLI now pass.

## Next

Phase 1: complete Docker-path CLI integration and local Qwen adapter execution, then Phase 3 toy product/harness.

## Boundaries

The older prototype under `src/asdi/` remains available for reference but is not the REV K Pass 1 implementation. Do not extend it to satisfy REV K requirements.
