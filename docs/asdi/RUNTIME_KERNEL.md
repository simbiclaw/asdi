# ASDI Runtime Kernel

ASDI-011 is a board-neutral process kernel. It does not contain Multica or Paperclip and does not call a board.

## Adapter registry

| Adapter | Executable discovery | `done_check` behavior | Launch authorization |
|---|---|---|---|
| `claude_code` | `claude` or explicit path | Requires explicit Stop-hook pass evidence | Container isolation required |
| `codex` | `codex` or explicit path | Launcher independently reruns `done_check` | Container isolation required |
| `hermes` | `hermes` or explicit path | Launcher independently reruns `done_check` | Container isolation required |
| `local_process_test` | Explicit absolute utility only | Launcher rerun | Explicit synthetic-test authorization; non-compliant |

`RuntimeAdapterConfig` requires an explicit executable and optional argv prefix/suffix. It can include or omit the contract objective. Commands are argv tuples; nested `archon`/ASDI orchestration commands are rejected.

## Durable run layout

```text
<store-root>/runs/<asdi_run_uuid>/
  run.json
  events.jsonl
  stdout.log
  stderr.log
  done_check.stdout.log
  done_check.stderr.log
  workspace/
```

`run.json` is atomically replaced. `events.jsonl` is append-only and fsynced. Each event has a schema version, monotonic sequence, run ID, UTC timestamp, type, and payload.

## States

`created` → `starting` → `running` → `runtime_succeeded` → `done_check_running` → `succeeded`

Failure/cancellation paths end only in `failed` or `cancelled`. Start failures include missing runtime, invalid runtime configuration, missing/unknown isolation, unsafe-start rejection, missing sandbox configuration, missing container runtime path, and `sandbox_setup_failed`. Recovery failures include `host_restart_orphaned`, `process_identity_changed`, `missing_process_identity`, and `host_restart_interrupted`.

## Security boundary at this ticket

- The launcher calls `validate_run_contract` at creation and again before start.
- Vendor runtime adapters require an explicit ASDI-012 sandbox. Enforced ASDI-012 is not accepted yet; an owner-approved `development_open` profile may run noncompliant development fixtures only.
- Synthetic host-process mode is explicitly labelled non-compliant and is restricted to allowed absolute utilities.
- The child environment does not inherit the launcher environment or secrets.
- The human environment is not production and no external runtime is invoked by this ticket.

Live turn, spend, and wall-clock enforcement is ASDI-013 and remains blocked. ASDI-012 has partial container evidence but its required container-side egress boundary is not accepted; autonomous operation remains disabled.
