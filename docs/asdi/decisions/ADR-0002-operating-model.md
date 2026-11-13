# ADR-0002: Operating Model Decisions

**Ticket:** ASDI-001  
**Date:** 2026-11-13  
**Owner:** Repository owner for unresolved items; implementation follows the stated working-design baseline for accepted items  
**Statuses:** see individual decision records below

## D-4 — Sensitive log/model privacy

**Status:** Proposed; local-only is the safe default until the owner confirms otherwise.

**Decision under consideration:** Use a local model for logs containing user data. API models may process only scrubbed logs. Until confirmation, any implementation handling sensitive logs must default to local-only and must not send raw user data to an external API.

**Rationale:** This prevents agent/telemetry workflows from exposing user data through third-party model providers while retaining an explicit owner decision.

**Evidence required to close:** Owner confirmation and a test proving raw-log routing stays local, scrubbed-log routing is recorded, and policy violations fail closed.

**Source:** Backlog §1.2 and §7.

## D-8 — Local event intake

**Status:** Proposed pending API-budget and status-semantics verification.

**Decision under consideration:** Use a local GitHub API poller every 60 seconds, with idempotent catch-up. No GitHub Actions, webhooks, or inbound webhook route.

**Rationale:** This preserves GitHub as passive code host and keeps event processing local, but API cost and status behavior are unverified for the actual repository and plan.

**Evidence required to close:** Measured request budget, pagination/catch-up behavior, duplicate-event handling, restart recovery, and exact status semantics against the selected GitHub repository/plan.

**Source:** Backlog §1.2 and §7; implementation is ASDI-031.

## Board and Archon source-of-truth split

**Status:** Accepted as the working-design baseline.

**Decision:** The board owns work items. Archon owns pipeline runs. A nightly reconciliation job detects drift between them; it does not silently choose one system as globally authoritative when ownership differs.

**Rules:**

- Work item identity, admission, type, state, and linkage belong to the board.
- Pipeline run identity, attempt, event stream, evidence, verdict, and outcome state belong to Archon.
- Cross-system references are stable IDs.
- Reconciliation reports drift and records corrective actions; it does not destroy evidence.
- Human admission remains required before agents may work on admitted feature work.

**Evidence required for production acceptance:** Reconciliation tests cover duplicate IDs, missing counterparts, restart during correction, stale links, and concurrent updates.

**Source:** Backlog §1.2 and ASDI-001.
