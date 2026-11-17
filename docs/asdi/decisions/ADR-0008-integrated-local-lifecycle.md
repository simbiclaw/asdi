# ADR-0008: Integrated Local Lifecycle Prototype

**Date:** 2026-11-15
**Owner:** Repository owner
**Status:** Accepted as a local, single-host lifecycle prototype; not accepted as production autonomy

## Context

Previous work proved individual runtime pieces but not a complete engineering company loop. Continuing to perfect sandbox plumbing before proving the company loop delayed the primary objective. The owner directed practical end-to-end integration on one Mac Studio, with network access available for development but protected resources and production secrets kept outside agent reach.

## Decision

Implement one integrated local lifecycle engine instead of separate subsystem prototypes:

```text
admission → brief → decomposition → execution → self-verification
→ three scoped independent checks → bounded repair → change classification
→ T0-authorized local merge → local deployment → default-off flag
→ controlled exposure → experiment verdict
→ production detection → triage → repair → redeploy → verification
→ closure/reopening → learning ledger
```

Fixture agents make this loop runnable now. They run as ordinary argv processes with a minimal environment, isolated mission workspace, and durable events. Live Claude Code/Codex/Hermes adapters can later implement the same agent contract without changing the lifecycle engine.

The local target supports actual atomic release switching, default-off flags, controlled exposure, health/load probes, defect records, rollback, verification, closure, and learning events.

## Governance and safety

The engine does not grant autonomous merge authority. Every local merge requires explicit `T0_human` authorization with approver and decision reference. Remote merge is disabled. Production access and irreversible actions remain false. Local flags start disabled and exposure records its decision reference.

## Consequences

- ASDI can now demonstrate both required integrated scenarios locally.
- The implementation includes an explicit shell-free command adapter and local per-mission guardrails so a real CLI can be substituted without redesign.
- This is not production autonomy: agents are deterministic fixtures, deployment is local, remote merge is disabled, strict container egress remains unaccepted, and turn/spend/wall-clock guardrails remain ASDI-013 work.
- The next high-value integration step is replacing the fixture agent with one live local runtime adapter while retaining admission, review, merge, deployment, monitoring, and learning evidence.
