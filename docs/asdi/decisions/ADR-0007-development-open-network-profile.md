# ADR-0007: Development-Open Network Profile

**Date:** 2026-11-15  
**Owner:** Repository owner  
**Status:** Accepted for development flow bring-up only; noncompliant with ASDI-012 acceptance

## Context

ASDI-012's intended no-network/Unix-socket egress transport is blocked on Docker Desktop/macOS because host Unix sockets cannot be bind-mounted into the Linux VM container. The owner then directed the implementation to prioritize completing the flow rather than keeping egress maximally restrictive in the interim.

## Decision

Add an explicit `development_open` run-contract network mode and matching sandbox profile.

It is valid only when all are true:

- `boundaries.network.mode` is `development_open`;
- `override_reason` is `owner_approved`;
- `override_reference` records the owner decision;
- `scope` is `development_only`;
- the launcher receives explicit `allow_noncompliant_test=true`.

The container uses a Docker bridge network. Runtime state, sandbox evidence, and flow reports must label it `development_open_noncompliant` and `isolation_compliant=false`. It does not authorize production access, production data, production credentials, irreversible actions, board integration, autonomous merge, or ASDI-012 acceptance.

## Consequences

- The launcher, done-check, structured events, cancellation, cleanup, and human-review handoff can be exercised end-to-end before the strict egress transport is chosen.
- Bridge networking can reach destinations that a compliant run must deny. Therefore this profile is unsafe for production data, scoped credentials, production networks, or autonomous operation.
- This is an explicit, auditable development exception. It must not be presented as ASDI-012 compliance or a successful hard-rule H3 result.
- Strict container-side egress remains required before autonomous operation. The previously recorded ASDI-012 result remains FAIL.
