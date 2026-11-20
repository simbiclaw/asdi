# ASDI-011 Runtime Launcher Evidence

**Date:** 2026-11-13
**Ticket:** ASDI-011
**Result:** **PASS at kernel/adapter-interface level; ASDI-012 is required before vendor runtime execution**

## Changed paths

| Path | Capability |
|---|---|
| [`src/asdi/runtime.py`](../../src/asdi/runtime.py) | Board-neutral run store, adapter interface, Claude/Codex/Hermes adapters, synthetic process adapter, launcher, cancellation, recovery, structured events, usage capture, launcher `done_check`, and durable failure states. |
| [`tests/test_runtime_adapters.py`](../../tests/test_runtime_adapters.py) | Separate adapter identity/command/error contracts, nested-orchestration rejection, and synthetic allowlist. |
| [`tests/test_run_launcher.py`](../../tests/test_run_launcher.py) | Invalid-contract preflight, actual cancellation, success/done-check, runtime failure, usage, host restart, missing identity, adapter lifecycle, executable resolution, and board neutrality. |
| [`docs/asdi/RUNTIME_KERNEL.md`](RUNTIME_KERNEL.md) | Runtime boundary and durable layout. |
| [`docs/asdi/decisions/ADR-0006-runtime-launch-boundary.md`](decisions/ADR-0006-runtime-launch-boundary.md) | Fail-closed launch decision. |
| [`docs/asdi/GATE_010_VERIFICATION.md`](GATE_010_VERIFICATION.md) | ASDI-010 acceptance verification. |

No ASDI-012 files, container runtime integration, egress policy, or board integration were added.

## Acceptance mapping

| Criterion | Evidence | Result |
|---|---|---|
| Contract tests exercise each adapter lifecycle/error handling | `ClaudeCodeAdapter`, `CodexAdapter`, and `HermesAdapter` tests cover separate identity, command template, done-check mode, missing executable, and common synthetic-process cancellation. Installed executables resolve without invocation. | Pass |
| Cancellation makes the child process exit | Dedicated controlled run started `/bin/sleep 30`; SIGTERM produced exit code `-15`; state reload remained `cancelled`. | Pass |
| Durable run identity and evidence | UUID `run.json`, append-only fsynced `events.jsonl`, stdout/stderr files, workspace marker, board reference, process birth identity. | Pass |
| Structured event collection | Sequence-checked JSONL events; structured JSON output; `usage_observed`; raw stream logs retained. | Pass |
| Runtime failure handling | `/usr/bin/false` ended durably as `failed/runtime_failure` with exit code 1 and skipped `done_check`. | Pass |
| Host restart failure handling | A running sleep exited while its launcher object was gone; new launcher recovery durably failed as `host_restart_orphaned`. | Pass |
| Missing executable failure | Claude adapter with nonexistent explicit path durably failed as `missing_runtime`. | Pass |
| Launcher verifies `done_check` | Successful synthetic runtime passed only after launcher rerun; Codex/Hermes adapters enable recheck. Claude requires Stop-hook evidence and otherwise fails `done_check_unverified`. | Pass |
| Usage is collected | Runtime emitted JSON usage `{usd_cost: 1.25, turns: 3}`; state and event persisted both values. | Pass |
| No nested orchestration/board coupling | Registry has no board names; `archon` runtime command rejected; only an optional opaque `board_task_reference` is stored. | Pass |

This ticket does **not** claim container isolation, descendant containment, egress enforcement, or autonomous operation.

## Execution evidence

Full suite:

```sh
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Result:

```text
Ran 29 tests in 1.513s
OK
```

Standalone cancellation run:

```json
{
  "cancel_requested": true,
  "cancelled_status": "cancelled",
  "durable_state_reloaded": true,
  "event_types": [
    "run_created",
    "contract_validated",
    "runtime_starting",
    "runtime_started",
    "cancel_requested",
    "process_cancelled"
  ],
  "exit_code": -15,
  "pid": 23613,
  "process_start_time": "1794568552:138165",
  "running_status": "running",
  "run_id": "asdi_run_0586bf9a-ff7b-4b8a-b79c-8b2083ecdef4",
  "signal": "SIGTERM"
}
```

The temporary evidence directory was outside the repository and is reproducible through `tests/test_run_launcher.py::RunLauncherTests::test_actual_process_cancellation_persists_terminal_evidence`.

## Actual runtime availability

Availability was checked with `shutil.which`, not invocation:

```json
{
  "claude": "/Users/russell/.local/bin/claude",
  "codex": "/Users/russell/.nvm/versions/node/v25.2.1/bin/codex",
  "hermes": "/Users/russell/.local/bin/hermes"
}
```

All three resolve, but the launcher intentionally returned a durable `sandbox_not_implemented` failure when a vendor adapter was requested with `isolation_mode="container"`. No vendor CLI was invoked.

## Unresolved issues and boundaries

1. Claude Code's actual Stop-hook output and command interface are not validated.
2. Codex and Hermes product command interfaces, authentication, output schemas, and runtime-specific error semantics are not validated.
3. Container-per-run isolation, workspace ownership, egress allowlist, descendant/process-group containment, and cleanup remain ASDI-012.
4. Live turn, spend, and wall-clock enforcement remains ASDI-013.
5. Durable run recovery cannot reconstruct a lost child's exit code; it intentionally records `host_restart_orphaned` rather than guessing.
6. H1 remains unenforced after ADR-0004, so no autonomous or merge path is authorized.

## Acceptance status

**ASDI-011 pass is limited to the board-neutral launcher interface, durable state/events, synthetic process lifecycle, failure/recovery handling, and fail-closed vendor adapter boundary.** ASDI-020 and vendor runtime integration remain blocked pending ASDI-012 and the D-9 owner decision.
