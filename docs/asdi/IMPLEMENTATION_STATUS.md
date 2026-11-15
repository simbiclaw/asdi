# ASDI Implementation Status

**Reconciled:** 2026-11-15
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
| ASDI-012 | ASDI-011 | **Fail / implementation in progress** | Hardened no-network container lifecycle, cancellation, workspace separation, environment boundary, and fail-closed setup have live evidence. Container-side egress does **not** pass because Docker Desktop/macOS cannot mount the host-side Unix socket. An owner-approved `development_open` bridge profile now permits noncompliant flow bring-up only. See [`GATE_012_EVIDENCE.md`](GATE_012_EVIDENCE.md), [`DEV_FLOW_EVIDENCE.md`](DEV_FLOW_EVIDENCE.md), and ADR-0007. |
| ASDI-013 | ASDI-010/011/012 | Local prototype guardrails verified; autonomous acceptance blocked | Mission turn, reported spend, wall clock, and bounded repair are enforced in the local lifecycle. Live runtime billing and production-quality enforcement remain unfinished, and ASDI-012 remains failed. |
| ASDI-014 | ASDI-011 | Partial | Durable state/events and a redacted JSON CLI now support mission/event/product/work-reference retrieval and guardrail/budget visibility. Retention policy, remote query interface, and production observability remain. |
| Work admission/reset | Integrated lifecycle | Local prototype verified | External references are queryable; two failed repair attempts produce a linked brief-v2 reset with fresh workspace/budget and preserved evidence. |
| Operations CLI | Integrated lifecycle | Local prototype verified | Durable JSON CLI supports admission, mission/event/product queries, guardrail/budget visibility, work-reference lookup, evidence redaction, and restart-safe state. |
| Autonomous mission runner | Integrated lifecycle | Local prototype verified | Durable admitted work orders can execute through checks, T0-governed local merge, local deployment, flags/exposure, and experiment verdict. Fixture agents verified; live agents still blocked on provider/model. |
| ASDI-020 | ASDI-001/011/012/013 | Blocked | D-9 spike requires the missing sandbox and guardrail capabilities and an owner board decision. |
| ASDI-021 through ASDI-022 | Gate 1 / D-9 | Blocked for board product integration | Local lifecycle admission/brief/decomposition exists, but board dispatch cannot start pending D-9. |
| ASDI-030 onward | Prior gates | Local prototype integration verified; production autonomy not accepted | Outcome workflow, local T0 merge, bounded repair, local deploy/rollback, default-off flags, experiment verdict, monitoring/triage/closure, and learning ledger are integrated. Remote merge, production deployment, live model agents, full review governance, and TRM promotion remain disabled or unfinished. See [`COMPANY_LIFECYCLE_EVIDENCE.md`](COMPANY_LIFECYCLE_EVIDENCE.md). |

## Hard-rule status

| Rule | Status |
|---|---|
| H1 merge authority | Not enforced; no autonomous merge. Owner deferred the GitHub protection path. |
| H2 enforced `done_check` | Contract and launcher recheck pass for tested local/container cases; complete enforcement remains ASDI-013. |
| H3 container-per-run and egress | **Not accepted.** Network-none/hardened container evidence exists, but container-side allowlist enforcement fails on current Docker Desktop. |
| H4 secrets outside sandbox | No persistent secret mount; tested host environment secret was absent in container. Production image/secret injection remains unapproved. |
| H5 per-run guardrails | Local prototype turn/spend/wall-clock enforcement is implemented and tested; live vendor billing and production acceptance remain unfinished. |
| H6 no irreversible actions | No irreversible agent action enabled; merge/deploy/production paths remain closed. |
| H7 protected generated/vendored paths | No protected generated/vendored implementation yet; repository governance remains incomplete. |

## Open owner decisions

1. **D-9 board choice** remains reserved.
2. **Pilot target** remains unselected.
3. **GitHub protection path** was deferred; H1 remains fail-closed.
4. **Production sandbox image and secret-injection boundary** must be selected and audited.
5. **Container egress transport on macOS/Docker Desktop** requires an architectural decision if this remains the host platform.
6. **ADR-0007 replacement** is required before autonomous operation: development-open bridge networking is noncompliant by definition.
7. **Live model agent integration** is required to replace deterministic fixture agents in the integrated company loop. The explicit command/Codex adapter paths exist; an initial live smoke attempt was stopped by the configured wall-clock guardrail and needs provider/runtime tuning or a faster local model decision.

## Current execution boundary

Synthetic host-process tests are allowed only for process-kernel testing. The owner-approved `development_open` profile may exercise the flow with no production credentials/data; it is explicitly noncompliant. The integrated local lifecycle uses fixture agents or an explicit command adapter, local deployment, and T0-authorized local merge only. No autonomous vendor runtime, remote merge, production deployment, or production exposure is authorized. ASDI-012 acceptance remains failed.
