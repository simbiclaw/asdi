# ASDI Pilot Target

**Ticket:** ASDI-002  
**Date:** 2026-11-13  
**Owner:** Repository owner  
**Status:** **Repository selected by owner; pilot service interface still blocked on owner design/approval**

## Finding

The inspected repository contained only [`ASDI_Codex_Implementation_Backlog_REV_H_G.md`](../../ASDI_Codex_Implementation_Backlog_REV_H_G.md) and the discovery artifacts added under `docs/asdi/`. It had no Git history at audit time and no deployable product, service, API, package manifest, Dockerfile, database, test suite, CI, metrics endpoint, feature-flag surface, or controlled defect path.

The owner designated the private repository `simbiclaw/asdi` as the ASDI repository. That repository remains the ASDI platform/control repository, not yet a selected pilot product. It still has no deployable product or service, so a synthetic reference service is **not** created because the backlog requires explicit owner approval before inventing one.

The repository currently contains no customer data and no production connectivity. It is therefore eligible only for synthetic-data platform validation until the owner selects or approves an actual pilot service.

## Owner decision required

The repository designation resolves only where ASDI itself is hosted. Select exactly one option for the lifecycle pilot:

1. **Designate an existing pilot repository/service**, suitable for controlled feature/release/defect validation, with synthetic or test data only.
2. **Approve a small synthetic reference service** in this repository for the first lifecycle demonstration.

Do not connect the pilot to real customer data, production traffic, real external side effects, or unapproved exposure.

## Minimum pilot interface for E2E acceptance

Once the owner selects the target, this document must be updated with repository, environment, owner approval, and exact implementation details:

| Interface | Minimum requirement |
|---|---|
| Deployable artifact | Reproducibly built and run locally; supports a known immutable version and safe rollback/termination. |
| Health surface | A local readiness/liveness endpoint or equivalent check with structured, machine-readable status. |
| Metrics surface | At least one local metrics endpoint or equivalent evidence stream suitable for release verification and defect diagnosis. |
| Feature-flag path | One controlled default-off flag that can be enabled only in a test environment, with observable behavior change and safe disable/rollback. |
| Defect injection | A test-only, reversible defect fixture or branch that can be introduced, observed, repaired, and verified without affecting shared data. |
| Data boundary | Synthetic/test data only; explicit inventory of external calls and proof that customer/production side effects are impossible. |

## Downstream effect

While this target is unselected:

- Feature-experiment E2E and production self-healing E2E tickets are blocked.
- Production exposure, release, traffic, migration, and external side effects remain prohibited.
- Board-neutral infrastructure work may continue only when its own ticket dependencies are satisfied.
- No mock product should be represented as the owner-selected pilot.
