# ASDI REV K implementation status

**Revision set:** REV K  
**Current pass:** Pass 1  
**Current phase:** Phase 1 — launcher and verifier (remediation cycle 1)

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

## Verification remediation workflow

The user-directed remediation/specification-escalation loop is implemented as a durable controller:

- Initial audit does not consume either remediation cycle.
- A failed audit runs at most two builder remediation cycles, each followed by a fresh configured verifier invocation.
- Candidate identity records the commit plus a dirty-worktree tree digest when applicable.
- A verifier-reported specification defect, `SPEC_*` blocked reason, or finding marked as a specification defect/conflict enters an immediate hold.
- A builder mutation of an authoritative specification enters an immediate hold without consuming the defect rule.
- Two persistent failures produce the required Specification Feedback Report and hold.
- Explicit owner decisions are recorded durably and release the hold with the selected disposition.

See [`docs/asdi/REMEDIATION_WORKFLOW_EVIDENCE.md`](docs/asdi/REMEDIATION_WORKFLOW_EVIDENCE.md).

## Specification hold

The independent initial audit found the long-known revision-metadata conflict: Design REV K calls the Trust Handbook `rev 2` / frozen, while the Handbook and Build Guide identify it as REV K / synchronized. This is recorded in [`docs/asdi/SPEC_FEEDBACK_HANDBOOK_SYNC.md`](docs/asdi/SPEC_FEEDBACK_HANDBOOK_SYNC.md). No specification text may be changed or reinterpreted, and no four-document synchronized acceptance claim may be made, until the owner selects a disposition. Independent implementation repair continues under the allowed parallel-progress rule.

## Next

Run a fresh independent conformance audit of remediation cycle 1. Continue Phase 1 Docker/local-model integration evidence only if that audit has no affected-work hold. Do not begin Phase 3 while the specification-sync acceptance claim remains held.

## Boundaries

The older prototype under `src/asdi/` remains available for reference but is not the REV K Pass 1 implementation. Do not extend it to satisfy REV K requirements.
