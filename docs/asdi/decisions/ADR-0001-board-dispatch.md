# ADR-0001: Board and Dispatch Platform

**Ticket:** ASDI-001  
**Date:** 2026-11-13  
**Status:** Deferred — blocked on repository owner review of ASDI-020 compatibility evidence  
**Owner:** Repository owner  
**Decision ID:** D-9

## Context

ASDI Design REV H identifies Multica as current but leaves D-9 open. ASDI Stack REV G recommends Paperclip for the single-host P-1 profile and scores Paperclip + Archon at 76/110 versus Multica + Archon at 75/110. The one-point difference is within scoring noise and is not a benchmark. Choosing from these scores alone would silently resolve an explicitly open owner decision.

The target profile is one Mac Studio M3 Ultra with 256 GB unified memory. Shared machine operation requires reliable cancellation, hard budget stops, heartbeats, recovery, and per-run isolation. Board-specific assumptions must remain behind a narrow adapter so run contracts, Archon pipelines, and GitHub integration remain board-neutral.

## Decision

No board is selected. D-9 remains explicitly blocked on owner decision until ASDI-020 executes the compatibility tests below and the owner reviews the operational evidence. Neither candidate may be implemented as though selected.

## Required compatibility test plan

The spike must test both Multica and Paperclip through their adapters and preserve task/run identity and evidence. A runtime-specific limitation may be documented with evidence in place of an available runtime.

### Test 1 — dispatch, persistence, and restart recovery

1. Dispatch equivalent tasks to Claude Code, Codex, and Hermes, or document the exact runtime limitation with logs and API evidence.
2. Record a stable task identity, run identity, adapter, runtime, work item, and board state.
3. Restart the board server during an active task.
4. Demonstrate recovery without duplicate work and reconcile board task state with Archon run state.

**Pass:** task/run identity survives restart; recovery is deterministic or fails durably; no duplicate build run starts; board and run states reconcile.

### Test 2 — cancellation, process containment, and budgets

1. Start a task and cancel it while running.
2. Prove that the runtime child process and its container stop, not merely that the board state changes.
3. Enforce and record spend and wall-clock limits.
4. Confirm cleanup leaves evidence but removes active compute and workspace access.

**Pass:** process and container terminate; descendants are contained; cancellation is durable; budget enforcement produces a structured failure; no orphan container or unauthorized workspace access remains.

### Test 3 — PR completion, linkage, and non-merge proof

1. Complete a controlled task against the pilot target and open a PR from the run's dedicated branch.
2. Attach the PR to the original work item.
3. Reconcile board state and Archon outcome state.
4. Attempt direct merge using the agent identity and verify that it fails.

**Pass:** PR and work item are linked; reconciliation detects state correctly; agent merge is denied; only the merge bot can enqueue an eligible, fully gated change.

## Candidate-specific checks

| Candidate | Required adapter check |
|---|---|
| Multica | Verify task-cancel API, wrapper-command runtime integration, per-run container launch, spend/wall-clock caps, restart recovery, and event reconciliation. |
| Paperclip | Verify cancellation through the adapter and prove the adapter receiver launches a per-run container; inspect hard stop and heartbeat behavior under shared-host contention. |

Each result must include exact commands/API calls, logs, timestamps, process/container IDs, network/workspace evidence, friction encountered, and durable state dumps. A feature checklist is not acceptance evidence.

## Consequences

- ASDI-020 can run only board-neutral groundwork plus this adapter compatibility spike.
- ASDI-021 is blocked until the owner explicitly accepts a board after review.
- Run contracts and downstream Archon/GitHub capabilities must not encode Multica or Paperclip assumptions.
- Failure of cancellation, containment, recovery, identity linkage, or merge denial fails D-9 for that candidate.
