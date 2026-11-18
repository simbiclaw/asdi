# ASDI REV K implementation status

**Revision set:** REV K
**Current pass:** Pass 1
**Current phase:** Phase 1 — launcher and verifier (Loop A human hold)

## Completed

- [x] Reference set imported under `reference/`.
- [x] REV H/G implementation backlog archived under `reference/archive/`; the four REV K specifications are recorded as the authoritative set in [`reference/AUTHORITY.md`](reference/AUTHORITY.md).
- [x] Owner-approved REV K metadata reconciliation completed: the Design and Handbook now record the four-document set as synchronized and classify rev-2/frozen language as historical.
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

## Specification authority decision

The former Handbook synchronization hold is **resolved by owner-approved specification reconciliation on 2026-11-18**. The Design introduction now names Trust Handbook REV K; its rev-2/frozen revision-log sentence is explicitly historical; Handbook §13 records that Build Guide V4 has already been synchronized at REV K. The current four-document hashes are pinned in [`reference/AUTHORITY.md`](reference/AUTHORITY.md), and the original finding remains auditable in [`docs/asdi/SPEC_FEEDBACK_HANDBOOK_SYNC.md`](docs/asdi/SPEC_FEEDBACK_HANDBOOK_SYNC.md).

This resolves the metadata synchronization blocker only. It does not independently accept implementation work or override the Loop A process hold.

The fresh cycle-2 verifier for candidate `19e6e2d` was stopped by the model provider's usage limit before producing a verdict. Its status is `verification_blocked`; no acceptance is claimed.

Strict verifier hardening now requires a launcher-collected `result.json` bound to the run and commit, with every feature passing and its negative control caught. Live Docker negative and positive runs both produced valid content-addressed evidence; the malformed verifier stayed red and the corrected fixture succeeded.

Phase 1 now has a per-run HTTP/CONNECT egress proxy attached to both the internal run network and `asdi-egress`. The agent receives only proxy URLs; the proxy performs destination authorization and injects the local model key. A live Docker run and separate proxy proof passed. The verifier-authored live coding-CLI slice is rejected from the active branch and preserved for reference; a fresh builder-owned implementation is still required.

## Next
Executing the owner's Option 3 decision with Option 2 preservation mechanics. All overreach candidates are retained at [`revk/preserved-verifier-overreach`](https://github.com/simbiclaw/asdi/tree/revk/preserved-verifier-overreach); the active PR branch is receiving non-destructive forward reverts before a fresh builder cycle and read-only audit.

## Boundaries

The older prototype under `src/asdi/` remains available for reference but is not the REV K Pass 1 implementation. Do not extend it to satisfy REV K requirements.
