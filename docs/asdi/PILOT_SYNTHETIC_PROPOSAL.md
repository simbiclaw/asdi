# Phase 3 synthetic pilot proposal — owner decision required

**Date:** 2026-11-18  
**Status:** **`toy-notes` approved on 2026-11-20 as a reversible provisional pilot by owner directive to continue autonomously toward the complete lifecycle. Implementation behind `config/pilot.yaml` may proceed. Phase 3 exit remains unproven until the product harness passes.**

## Decision required

The owner selected the smallest synthetic reference service proposed below; the pilot must use synthetic/test data only. The recorded decision is in `state/owner-decisions.jsonl` with decision id `owner_decision_732eca91-f156-46e9-a4b7-224e2ae8dc4b`. A later owner decision can replace the provisional selection.

## Recommendation: `toy-notes`

A single-process local service in the ASDI workspace, intentionally thin enough to exercise every Pass 1 lifecycle stage without introducing production complexity.

### Runtime and storage

- Python standard library HTTP server; no additional framework.
- SQLite file under a run-owned data directory.
- Immutable local version and rollback by process/image identity.
- No external network calls; no customer or production data.

### Minimum user-visible surfaces

| Surface | Behavior |
|---|---|
| CLI | Create, list and read a note; export notes as JSON. |
| HTTP | `GET /healthz`, `GET /readyz`, `GET /metrics`, `GET /notes`, `POST /notes`. |
| UI | Local read-only note list and create form served from the same process. |

### Lifecycle controls

| Control | Minimum implementation |
|---|---|
| Feature flag | `notes_ui_enabled`, default off; enabling changes the UI route response only. |
| Health/readiness | Process and SQLite checks return machine-readable JSON. |
| Metrics | Local Prometheus text endpoint with request count, latency and process metrics. |
| Defect injection | Test-only environment flag causes note creation to fail; reversible by restart/environment change. |
| Rollback | Keep previous immutable build directory; deployment swaps and can swap back after failed smoke. |

### Verification scope

Phase 3 will build `verify/` with at least three features across CLI, HTTP and UI, each with a negative control. Static gates cover compile, unit checks and secret scanning. The product harness must self-test and detect each deliberately broken feature.

## Alternatives

1. **Select an existing repository/service.**
   - Advantage: avoids a synthetic product.
   - Disadvantage: no eligible pilot repository is currently visible in the workspace; requires owner-provided path and safety review.
2. **Approve `toy-notes`.**
   - Recommended: satisfies Phase 3 features across CLI/HTTP/UI with minimal infrastructure.
3. **Defer Phase 3.**
   - Advantage: no new product.
   - Disadvantage: lifecycle cannot reach first light or full loop.

## Decision required

Reply with one of: **select existing pilot `<path>`**, **approve `toy-notes`**, or **defer Phase 3**. No pilot-dependent implementation begins before explicit approval.
