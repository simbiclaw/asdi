# ASDI Decision Index

| ADR | Decision | Status | Owner | Source |
|---|---|---|---|---|
| [ADR-0001](ADR-0001-board-dispatch.md) | Board and dispatch platform for D-9 | **Deferred — blocked on owner review of ASDI-020 evidence** | Repository owner | Backlog §1.3 and §7 |
| [ADR-0002](ADR-0002-operating-model.md) | Log/model privacy, event intake, and source-of-truth split | Mixed: D-4 proposed/local-only-safe-default; D-8 proposed pending budget verification; source-of-truth accepted | Repository owner for D-4/D-8; implementation follows working design for source split | Backlog §1.2, §1.4, and §7 |
| [ADR-0003](ADR-0003-deployment-and-parameters.md) | Deployment topology, providers, reservations, SLOs, and operational thresholds | **Deferred — no values selected or invented** | Repository owner | Backlog §1.2 and §7 |

Statuses are limited to `proposed`, `accepted`, `rejected`, and `deferred`. A deferred decision does not authorize implementation of a downstream capability that depends on it.

## Owner actions required

1. Review the D-9 test evidence from ASDI-020 and choose Multica, Paperclip, or another supported board after the compatibility spike.
2. Confirm D-4 sensitive-log model policy and authorize verification of the D-8 polling budget.
3. Select deployment topology and provider values in ADR-0003 before production infrastructure implementation.
