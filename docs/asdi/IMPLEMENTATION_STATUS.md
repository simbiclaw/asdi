# ASDI Implementation Status

**Reconciled:** 2026-11-13  
**Branch:** `asdi/asdi-012-container-sandbox`  
**Authority:** ASDI Design REV H and ASDI Stack REV G

This is the live reconciliation record. Detailed acceptance evidence remains in the gate documents linked below.

| Ticket | Dependency | Status | Current position and blocker |
|---|---|---|---|
| ASDI-000 | None | Pass | Repository audit and implementation map are recorded in [`IMPLEMENTATION_MAP.md`](IMPLEMENTATION_MAP.md). |
| ASDI-001 | ASDI-000 | Pass | Initial architecture and unresolved decision ADRs are in [`decisions/`](decisions/README.md). D-9 remains open by definition. |
| ASDI-002 | ASDI-000 | Blocked | See [`PILOT_TARGET.md`](PILOT_TARGET.md). Owner has not selected a pilot product/service or approved a synthetic target. |
| ASDI-003 | ASDI-000 | Fail-closed / deferred | Owner deferred GitHub-native protection in ADR-0004. No scoped execution identity, merge authority, or autonomous merge path is enabled. See [`GATE_003_EVIDENCE.md`](GATE_003_EVIDENCE.md). |
| ASDI-010 | ASDI-000 | Pass | Contract schema, defaults, provenance, fixtures, validation, and launch preflight pass. See [`GATE_010_EVIDENCE.md`](GATE_010_EVIDENCE.md) and [`GATE_010_VERIFICATION.md`](GATE_010_VERIFICATION.md). |
| ASDI-011 | ASDI-010 | Pass | Board-neutral durable launcher, Claude/Codex/Hermes adapters, real child cancellation, events/usage/failure/recovery, and `done_check` recheck pass at kernel level. Vendor CLI invocation remains intentionally unverified. See [`GATE_011_EVIDENCE.md`](GATE_011_EVIDENCE.md). |
| ASDI-012 | ASDI-011 | **Fail / implementation in progress** | Hardened no-network container lifecycle, cancellation, workspace separation, environment boundary, and fail-closed setup have live evidence. Container-side egress does **not** pass because Docker Desktop/macOS cannot mount the host-side Unix socket. See [`GATE_012_EVIDENCE.md`](GATE_012_EVIDENCE.md). |
| ASDI-013 | ASDI-010/011/012 | Blocked | Cannot start while ASDI-012 is failed. Existing launcher `done_check` recheck does not satisfy live turn/spend/wall-clock acceptance. |
| ASDI-014 | ASDI-011 | Partial | Run state, JSONL events, usage, sandbox, egress decisions, and cleanup evidence are persisted. Queryable retrieval, retention/redaction policy, and full event schema/observability interface remain. |
| ASDI-020 | ASDI-001/011/012/013 | Blocked | D-9 spike requires the missing sandbox and guardrail capabilities and an owner board decision. |
| ASDI-021 through ASDI-022 | Gate 1 / D-9 | Blocked | Board integration and admission are explicitly out of scope pending D-9. |
| ASDI-030 onward | Prior gates | Not started / blocked | Outcome workflow, poller, review, merge policy, repair, TRM, metrics, production infrastructure, experiments, telemetry, and autonomy rollout are not enabled. |

## Hard-rule status

| Rule | Status |
|---|---|
| H1 merge authority | Not enforced; no autonomous merge. Owner deferred the GitHub protection path. |
| H2 enforced `done_check` | Contract and launcher recheck pass for tested local/container cases; complete enforcement remains ASDI-013. |
| H3 container-per-run and egress | **Not accepted.** Network-none/hardened container evidence exists, but container-side allowlist enforcement fails on current Docker Desktop. |
| H4 secrets outside sandbox | No persistent secret mount; tested host environment secret was absent in container. Production image/secret injection remains unapproved. |
| H5 per-run guardrails | Not implemented; ASDI-013 remains blocked. |
| H6 no irreversible actions | No irreversible agent action enabled; merge/deploy/production paths remain closed. |
| H7 protected generated/vendored paths | No protected generated/vendored implementation yet; repository governance remains incomplete. |

## Open owner decisions

1. **D-9 board choice** remains reserved.
2. **Pilot target** remains unselected.
3. **GitHub protection path** was deferred; H1 remains fail-closed.
4. **Production sandbox image and secret-injection boundary** must be selected and audited.
5. **Container egress transport on macOS/Docker Desktop** requires an architectural decision if this remains the host platform.

## Current execution boundary

Synthetic host-process tests are allowed only for process-kernel testing. No autonomous vendor runtime is authorized. The current ASDI-012 implementation may run only explicit no-network compatibility probes and must not be used for autonomous work.
