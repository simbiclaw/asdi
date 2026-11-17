# Adapter Interface and Guardrails Evidence

**Date:** 2026-11-15
**Result:** **Local prototype PASS** — live model service was not invoked

## What was added

* `CommandAgent`: an explicit, shell-free argv adapter.
* `MissionGuardrails`: per-mission turn, spend, and wall-clock limits.
* Durable `budget` evidence on every mission.
* A `--live-agent-command` path for the company scenarios.
* Guardrail transition `guardrail_exceeded` with machine-readable breach reasons.

The adapter accepts token substitution for `{workspace}`, `{mission_id}`, `{objective}`, and `{variant}`. It does not use a shell and requires an absolute executable. This allows a local Claude Code/Codex/Hermes CLI command to be substituted without changing the lifecycle engine.

## Live-CLI smoke attempt

A Codex-specific adapter was added at [`scripts/codex_lifecycle_adapter.py`](../scripts/codex_lifecycle_adapter.py). It invokes `codex exec` in workspace-write mode, validates the requested artifacts, and records stdout/stderr.

One opt-in integration attempt used the installed Codex CLI against a temporary local target. The lifecycle engine stopped it at the configured wall-clock guardrail after 300 seconds with `guardrail_exceeded`. No production resource was contacted by ASDI and no merge/deployment occurred. This is a live-agent integration failure, not a guardrail failure; the guardrail behaved correctly.

Follow-up diagnostics found the configured default provider was initially unreachable without the local proxy. With proxy and `CODEX_HOME` configured, `deepseek-v4.1-flash` and `glm-5.3-flash` both reached the provider but disconnected before response completion. This is now a provider/model integration issue rather than a lifecycle-engine issue.

## Verification

```sh
PYTHONPATH=src:. python3 scripts/run_company_scenarios.py
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

Latest integrated scenario result: **PASS**.
Evidence root:
`/private/var/folders/yf/nn0v06c92fv8yc2z36cqqjw80000gn/T/asdi-company-20261115-070326-frgvzumk`

Both missions used:

```json
{
  "max_turns": 24,
  "max_spend_usd": 2.0,
  "wall_clock_seconds": 120
}
```

Observed budgets:

* Product mission: 5 turns, $0.00, 0.271 seconds.
* Repair mission: 5 turns, $0.00, 0.266 seconds.

The default integrated run still used the deterministic fixture agent. The new command adapter was exercised separately by regression tests, including a shell-free explicit argv invocation.

## Guardrail regression evidence

Four tests prove hard transitions:

| Test | Result |
|---|---|
| Explicit command adapter runs without shell and charges one turn | Pass |
| At-turn limit blocks the next mission turn | Pass |
| Reported/default spend reaching limit blocks completion | Pass |
| Elapsed mission wall clock blocks execution | Pass |

Breaches persist as `guardrail_exceeded`, with the relevant budget and limits in mission state and the event log.

## Truthful limits

* A live model CLI has not yet been invoked in the integrated scenarios.
* Spend is enforced from adapter-reported/default cost; it does not yet query a vendor billing API.
* Wall clock covers mission age from admission through lifecycle operations.
* Container egress and process-tree isolation remain ASDI-012 work and are not accepted.
* The command adapter does not authorize production, remote merge, or irreversible actions.
