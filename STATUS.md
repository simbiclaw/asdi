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

**Live boundary update (2026-11-17):** the actual Docker scaffold topology probe proved that an `asdi-agent` container cannot reach a live listener on `asdi-prod` (`Network is unreachable`). A real Phase 1 fixture run initially failed closed because the verifier passed `destination=/opt/base:ro` to Docker `--mount`; Docker treated the suffix as part of the destination. The base volume was populated, but `/opt/base` was absent. Changing the mount to `destination=/opt/base,readonly` fixed the verifier. The corrected run completed with `status=succeeded`; static and base-harness checks were `pass`; the evidence manifest was valid and bound to fixture commit `726950b7ea027f0914b59d7b97b12bb37544cc9c`; and runtime evidence recorded no Docker socket and no mounted secrets. This is fixture-path boundary evidence, not toy-harness or Phase 1 completion evidence.

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

Phase 1 now has a per-run HTTP/CONNECT egress proxy attached to both the internal run network and `asdi-egress`. The agent receives only proxy URLs; the proxy performs destination authorization and injects the local model key. A live Docker run and separate proxy proof passed.

The remaining live coding-CLI gap is now closed with Claude Code `2.1.283`: run `r-b73ef259-c3e7-44ff-9d5f-1aa8d9dd77cb` used the proxy for Git, npm and local-model traffic; npm pinned `is-odd@3.0.1`; the proxy logged authorized `github.com:443` and `registry.npmjs.org:443` CONNECTs; the agent had no credential-like environment names; and the Claude Stop hook passed. The independent base-branch verifier re-ran the generated probe and caught its negative control. Evidence manifest `m-14f6e99b3711391703429abc` validated after teardown. See [`docs/asdi/REV_K_LIVE_EGRESS_CLI_EVIDENCE.md`](docs/asdi/REV_K_LIVE_EGRESS_CLI_EVIDENCE.md).

**Builder hardening update (2026-11-17):** the REV K launcher now records a terminal `failed` or `guardrail_exceeded` state for launch, agent, verifier and evidence failures; persists the launcher PID and complete run-resource inventory; and tears down the agent/proxy/network/volumes on normal, failed and killed paths. `launcher kill` now cleans all persisted run resources. Static-gate results preserve `blocking`, only blocking checks authorize green, and timeout remains `error`. The evidence verifier now rejects schema/result mismatch, statement/result disagreement, unsafe or unrecorded object paths, altered hashes or sizes, missing environment/tool bindings, and feature evidence without a matching stored object. The egress proxy connects to the address validated during destination authorization, closing a hostname re-resolution/DNS-rebinding window.

## Loop A human hold

Both remediation cycles are exhausted. Two verifier agents crossed their read-only authority and implemented work instead of returning only findings; the latest verifier-overreach commit is local-only `b5c187d`. Root independently validated 100/100 tests with four expected skips, but this is not independent acceptance. Phase 1 acceptance, Phase 3, merge, deployment and exposure are held pending owner direction. See [`docs/asdi/LOOP_A_ESCALATION.md`](docs/asdi/LOOP_A_ESCALATION.md).

## Next

Wait for explicit owner direction on [`docs/asdi/LOOP_A_ESCALATION.md`](docs/asdi/LOOP_A_ESCALATION.md). No further affected implementation, verifier retry, merge, deployment or exposure may proceed until then. The former specification-sync hold is resolved, but Phase 1 remains unaccepted. The latest hardening slice has local evidence only: 100 tests passed and four host-sensitive socket-binding tests were skipped; this is not an independent audit or phase-acceptance claim.

## Boundaries

The older prototype under `src/asdi/` remains available for reference but is not the REV K Pass 1 implementation. Do not extend it to satisfy REV K requirements.
