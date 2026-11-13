# ADR-0006: Runtime Launch and Process Identity Boundary

**Ticket:** ASDI-011
**Date:** 2026-11-13
**Owner:** Repository owner may override
**Status:** Accepted for kernel/adapter-interface implementation; ASDI-012 remains required for autonomous execution

## Context

ASDI-011 requires process lifecycle, cancellation, durable identity, structured events, and runtime adapters. Hard rule H3 still requires container-per-run isolation, and ADR-0004 leaves H1 unenforced. The host is macOS; its Python-spawned `ps` probe was denied in the controlled environment, while Darwin's `libproc` process-birth record is available without an external dependency.

## Decision

Implement a standard-library process kernel and four explicit adapters: Claude Code, Codex, Hermes, and `local_process_test`. Vendor adapters are `development_safe=false` and fail closed when `isolation_mode="container"` because ASDI-012 is not implemented. The synthetic adapter permits only a small absolute-utility allowlist, requires explicit `allow_noncompliant_test=true`, records `host_process_test_noncompliant`, and is prohibited from autonomous or production work.

Persist a UUID run identity plus Darwin process PID and birth seconds/microseconds. If platform or process identity cannot be verified, startup fails. The launcher environment passes only run identity and fixed safe paths; it does not forward the parent environment.

ASDI-011 cancellation sends `SIGTERM` to the direct child and may escalate to `SIGKILL`. This proves child-process cancellation, not container or full-descendant containment. Those claims remain reserved for ASDI-012.

## Consequences

- Installed Claude, Codex, and Hermes executables may be resolved without invocation, but cannot start through the launcher until ASDI-012 supplies a verified container boundary.
- A recovered run cannot invent an exit code. If the process disappears while the launcher is down, recovery is a durable `host_restart_orphaned` failure.
- Runtime usage is observed and persisted, but turn/spend/wall-clock enforcement is deferred to ASDI-013.
- A successful Codex/Hermes runtime still requires a passing launcher `done_check`. Claude success requires explicit Stop-hook pass evidence; absence is `done_check_unverified`.
