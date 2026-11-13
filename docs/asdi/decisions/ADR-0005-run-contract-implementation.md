# ADR-0005: Initial Run-Contract Implementation

**Ticket:** ASDI-010
**Date:** 2026-11-13
**Owner:** Repository owner may override
**Status:** Accepted for the non-executing ASDI-010 validator

## Context

The repository had no language, runtime, package manager, or dependency policy. ASDI-010 requires a machine-validatable contract and fixtures, while ADR-0004 disables all runtime execution and the backlog discourages unnecessary stack installation.

## Decision

Implement the first run-contract validator in Python using only its standard library. Expose a reusable validation function and a small CLI. Do not add JSON Schema, Pydantic, packaging metadata, a runtime launcher, container support, or an external dependency in this ticket.

The choice is reversible and scoped to contract validation. It does not select the implementation language for future product pilots or components.

## Consequences

- Tests use `unittest` and run with `PYTHONPATH=src`; packaging can be introduced later through a separately reviewed ticket.
- The absence of a launcher is intentional. An invalid contract cannot be launched because no launch path exists.
- A future launcher must call `validate_run_contract` before creating a run and must fail durably on `RunContractValidationError`.
