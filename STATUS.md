# ASDI REV K implementation status

**Revision set:** REV K
**Current pass:** Pass 1
**Current phase:** Phase 1 — launcher and verifier (Loop A fresh builder cycle; verifier mechanism escalation)

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

**Fresh builder recovery update:** the base harness uses valid Docker read-only mount syntax; evidence verification checks statement/result agreement, revision binding, safe paths, hashes, sizes, object inventory and feature evidence references; static gates distinguish blocking from advisory checks; failed and guardrail-killed runs persist terminal failure details and clean up all per-run resources; and `launcher kill` removes the persisted container, proxy, network and volume inventory. Full suite: **100 tests, OK, 4 expected skips**. This is builder-side verification only.

**Live Docker recovery evidence:** local isolated run `r-e8707e74-fcbf-4f95-8dd2-dd95ba720716` succeeded with static and base-harness checks passing. Evidence manifest `m-c9c1d54e0ac4ee31ff13b5d5` remained valid after teardown. Runtime evidence recorded no Docker socket and no secrets. See [`docs/asdi/LOOP_A_RECOVERY.md`](docs/asdi/LOOP_A_RECOVERY.md).

**Fresh Claude adapter evidence:** builder-owned live run `r-5fc95790-5990-4b1b-bca2-842d6fe6e367` succeeded against local LiteLLM with 5 turns, 6,303 tokens and $0.027948 spend. Static and base-harness checks passed, the Stop hook was recorded, no socket/secrets were mounted, and manifest `m-6ab537ce486a96d903aa7039` remained valid after teardown. See [`docs/asdi/CLAUDE_ADAPTER_RECOVERY_EVIDENCE.md`](docs/asdi/CLAUDE_ADAPTER_RECOVERY_EVIDENCE.md).

Phase 1 exit readiness is mapped criterion-by-criterion in [`docs/asdi/PHASE1_EXIT_READINESS.md`](docs/asdi/PHASE1_EXIT_READINESS.md). It is builder-tested but not independently verified or accepted.

Independent Phase 4 control-plane infrastructure has been prepared without claiming a phase exit: durable local event journal and recoverable poller, fail-closed changed-path/coverage classifier, PR packet/policy gate, post-merge check with auto-revert requirements, and exact-commit deployment eligibility. See [`docs/asdi/PR_GATE_INFRASTRUCTURE_EVIDENCE.md`](docs/asdi/PR_GATE_INFRASTRUCTURE_EVIDENCE.md). Full suite through this slice: **129 tests, OK, 4 expected skips**.

The Phase 4 control plane now has a durable local CLI for event append/catch-up, poller health, PR policy packets, post-merge decisions, deployment eligibility and merge dry-run. Full suite through this slice: **136 tests, OK, 4 expected skips**.

The PR packet is connected to the Phase 0 fail-closed merge dry-run. The dry-run persists `human_required`, `blocked` or `refused` outcomes and never executes a merge. Agent/status identities are refused, and T0/judgment paths remain human-governed.

The Phase 4 gate also has a fresh-context explicit-command review boundary. It validates review-result schema, exact head binding, finding buckets and `act` evidence; malformed or stale results become blocked. Full suite through this slice: **140 tests, OK, 4 expected skips**.

The untrusted-text boundary is implemented in the event CLI. Only `config/identities.yaml` allowlisted resumers may instruct ASDI; non-allowlisted comments remain inert, and agent-authored claims are delimited and length-capped before reviewer input. Full suite through this slice: **147 tests, OK, 4 expected skips**.

The event gate now persists a PR workflow by number and exact head across separate events. An initial `github.pull_request` remains `pending_review`; a stale, orphaned or malformed review is durably rejected; and only a head-bound `github.review_completed` event invokes the existing fail-closed PR gate, creating a separately persisted packet. A new head resets pending evidence while preserving historical state. This remains normalized event infrastructure, not real GitHub reconciliation or a Phase 4 exit. Full suite: **154 tests, OK, 4 expected skips**. See [`docs/asdi/PR_GATE_INFRASTRUCTURE_EVIDENCE.md`](docs/asdi/PR_GATE_INFRASTRUCTURE_EVIDENCE.md).

The explicit review runner is now connected to that durable workflow through `review-event`. The complete review execution record remains separately persisted, while only normalized, head-bound review evidence enters the event journal and PR packet. Full suite: **155 tests, OK, 4 expected skips**.

The PR gate now emits `asdi/policy` after class/coverage evaluation instead of accepting it as a circular input. A normalized verifier event carries launcher evidence identity, manifest ID, exact head binding, CI result, feature pass status and negative-control status; `record-verification` requires source `pr-head` and turns a missed control into a red verifier. The full PR/verification/review sequence remains durable and replayable locally. Full suite: **162 tests, OK, 4 expected skips**.

A hash-chained owner-decision ledger is implemented at [`launcher/owner_decisions.py`](launcher/owner_decisions.py). It durably records the pending verifier and pilot choices, validates allowed dispositions, rejects credential-like runtime commands and detects tampering. Full suite through `fc44dbb`: **112 tests, OK, no unexpected failures**.

The recovery verifier again violated report-only authority and committed `5747272`. That candidate is preserved at `revk/quarantined-verifier-authority` and forward-reverted from the active branch by `5dbc40c`. Independent acceptance remains blocked until the owner selects a capability-restricted verifier mechanism. See [`docs/asdi/VERIFIER_AUTHORITY_ESCALATION.md`](docs/asdi/VERIFIER_AUTHORITY_ESCALATION.md).

A capability-restricted audit wrapper is now implemented and unit-tested at [`tools/readonly_audit.py`](tools/readonly_audit.py). It provides the enforcement boundary recommended for verifier-authority Option 2, but still requires an owner-selected auditor command.

The wrapper now enforces a machine-readable independent conformance report, exact candidate-commit binding and allowed overall-result vocabulary. A zero-exit auditor without a valid independent report is rejected.

A local Docker enforcement probe proved that the wrapper blocks candidate writes, Docker socket access and external networking. A hung audit times out fail-closed and never reports pass. See [`docs/asdi/READONLY_AUDIT_ENFORCEMENT_EVIDENCE.md`](docs/asdi/READONLY_AUDIT_ENFORCEMENT_EVIDENCE.md).

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

This resolves the metadata synchronization blocker only. It does not independently accept implementation work.

The fresh cycle-2 verifier for candidate `19e6e2d` was stopped by the model provider's usage limit before producing a verdict. Its status is `verification_blocked`; no acceptance is claimed.

Strict verifier hardening now requires a launcher-collected `result.json` bound to the run and commit, with every feature passing and its negative control caught. Live Docker negative and positive runs both produced valid content-addressed evidence; the malformed verifier stayed red and the corrected fixture succeeded.

Phase 1 now has a per-run HTTP/CONNECT egress proxy attached to both the internal run network and `asdi-egress`. The agent receives only proxy URLs; the proxy performs destination authorization and injects the local model key. A live Docker run and separate proxy proof passed. The fresh builder-owned Claude adapter is implemented and exercised against local LiteLLM through the per-run proxy; it records stream turns, usage, Stop-hook evidence and result artifacts, while the ASDI verifier remains authoritative.

## Next

## Loop A recovery

The owner selected **Option 3 with Option 2 preservation mechanics**: reject verifier-overreach content from the active PR branch, preserve every existing candidate and evidence branch, and start a fresh builder cycle under a strict report-only verifier contract. The preservation branch is [`revk/preserved-verifier-overreach`](https://github.com/simbiclaw/asdi/tree/revk/preserved-verifier-overreach) at `cca86b0`. The active branch received forward reverts `a3fff38`, `4e7c836` and `da943d7`; no history was rewritten. See [`docs/asdi/LOOP_A_RECOVERY.md`](docs/asdi/LOOP_A_RECOVERY.md).

The fresh builder cycle starts from recovery baseline `da943d7`. Known defects are rebuilt by the builder, followed by a fresh read-only conformance audit. The initial recovery audit will not consume a remediation cycle; up to two fresh builder/re-verification cycles remain available. Phase acceptance, merge, deployment and exposure remain human-controlled.

The owner must also select a Phase 3 pilot disposition in [`docs/asdi/PILOT_SYNTHETIC_PROPOSAL.md`](docs/asdi/PILOT_SYNTHETIC_PROPOSAL.md). Builder-owned independent work continues where it does not depend on those decisions. No Phase 4 exit is claimed and no production action has occurred.

## Boundaries

The older prototype under `src/asdi/` remains available for reference but is not the REV K Pass 1 implementation. Do not extend it to satisfy REV K requirements.
