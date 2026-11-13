# ASDI Decision Index

| ADR | Decision | Status | Owner | Source |
|---|---|---|---|---|
| [ADR-0001](ADR-0001-board-dispatch.md) | Board and dispatch platform for D-9 | **Deferred — blocked on owner review of ASDI-020 evidence** | Repository owner | Backlog §1.3 and §7 |
| [ADR-0002](ADR-0002-operating-model.md) | Log/model privacy, event intake, and source-of-truth split | Mixed: D-4 proposed/local-only-safe-default; D-8 proposed pending budget verification; source-of-truth accepted | Repository owner for D-4/D-8; implementation follows working design for source split | Backlog §1.2, §1.4, and §7 |
| [ADR-0003](ADR-0003-deployment-and-parameters.md) | Deployment topology, providers, reservations, SLOs, and operational thresholds | **Deferred — no values selected or invented** | Repository owner | Backlog §1.2 and §7 |
| [ADR-0004](ADR-0004-github-protection.md) | GitHub repository rulesets and legacy branch protection | **Deferred — owner declined current GitHub-native enforcement; execution/merge remain disabled** | Repository owner | ASDI-003 probe evidence |
| [ADR-0005](ADR-0005-run-contract-implementation.md) | Initial ASDI-010 implementation approach | Accepted for non-executing validator: Python standard library only, no external dependency | Repository owner may override | ASDI-010 evidence |
| [ADR-0006](ADR-0006-runtime-launch-boundary.md) | ASDI-011 process launch and identity boundary | Accepted: synthetic host-process tests only; vendor CLIs fail closed without ASDI-012 | Repository owner may override | ASDI-011 evidence |

Statuses are limited to `proposed`, `accepted`, `rejected`, and `deferred`. A deferred decision does not authorize implementation of a downstream capability that depends on it.

## Owner actions required

1. Review the D-9 test evidence from ASDI-020 and choose Multica, Paperclip, or another supported board after the compatibility spike.
2. Confirm D-4 sensitive-log model policy and authorize verification of the D-8 polling budget.
3. Select deployment topology and provider values in ADR-0003 before production infrastructure implementation.
