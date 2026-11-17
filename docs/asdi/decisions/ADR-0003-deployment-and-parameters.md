# ADR-0003: Deployment Topology and Operational Parameters

**Ticket:** ASDI-001
**Date:** 2026-11-13
**Owner:** Repository owner
**Status:** Deferred — no topology or numeric threshold is selected; do not treat illustrative values as approved

## Context

The target is one Mac Studio M3 Ultra with 256 GB unified memory, divided into product-serving, agent, integration, and production zones. The backlog requires several provider and resource decisions but explicitly forbids inventing values. Some numeric values are illustrative defaults only.

## Deferred decisions and required evidence

| Decision | Status | Constraint | Required owner-facing evidence before acceptance |
|---|---|---|---|
| Database topology | Open | One Postgres server with two databases or two instances | Backup/restore boundary test, failure isolation, connection budget, migration safety, and local disk resource measurements |
| VM manager | Open | Must fit P-1 and support role isolation and resource reservations | Compatibility test, CPU/memory isolation, startup/recovery, cancellation, and host-contention behavior |
| Tunnel provider | Open | No inbound route into the agent zone | Route matrix, TLS/certificate behavior, reconnect behavior, ingress isolation, and secret storage |
| Proxy | Open | Traefik or Caddy are candidates | P-1 integration test, route/reload behavior, metrics, TLS, resource use, and failure mode |
| CPU/memory reservations | Open | Values unspecified | Benchmarks for product serving, builds, agent pool, CI, Postgres, and telemetry under representative load |
| SLO and error budget | Open | Values unspecified | Owner-approved availability/latency/error-budget targets and preemption/rollback thresholds |
| Defect severity threshold | Open | Scoring dimensions specified; threshold unspecified | Owner-approved severity formula, examples, and charter threshold |
| Experiment sample/power thresholds | Open | Product-specific; no generic threshold may be invented | Per-experiment metric, minimum exposure, power/MDE calculation, duration, and stopping rule |
| Diff budget | Provisional | 400 changed lines is illustrative | Owner confirmation and evidence from representative agent diffs/policy outcomes |
| Run guardrails | Provisional | 200 turns / USD 8 / 90 minutes are illustrative | Owner confirmation after observed run cost, duration, and failure behavior |
| Experiment WIP and expiry | Provisional | 3 concurrent / 14 days are starting defaults | Owner confirmation against experiment capacity and product traffic |
| Production verification window | Provisional | 72 hours is a starting default | Owner confirmation and evidence from controlled deployment/rollback verification |
| Domain, TLS, traffic, backup target | Open | Not specified | Named domain/DNS plan, certificate issuance, exposure path, encrypted backup target, and restore drill |

## Source-of-truth boundary

This ADR records open decisions and does not silently choose values. Each implementation ticket that consumes a parameter must load it from explicit configuration, fail closed when absent, and preserve provenance for the selected value.

## Consequences

- ASDI-060 and later production/infrastructure tickets remain blocked on the relevant topology, provider, reservation, SLO, threshold, domain, and backup decisions.
- Guardrails may be represented as configurable provisional defaults in a run contract only when clearly marked unapproved; they cannot authorize autonomous production access or merge.
