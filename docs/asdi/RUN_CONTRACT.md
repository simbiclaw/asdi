# ASDI Run Contract v1

ASDI-010 defines the machine-validatable contract that must exist before a launcher may create a run. This document describes the initial schema; the implementation and fixtures are the executable source of validation behavior.

## Design

- Five fields are authored for every run: `objective`, `why`, `constraints`, `out_of_scope`, and `done_check`.
- Empty `constraints` and `out_of_scope` arrays are valid when those items are genuinely absent.
- Platform fills `boundaries`, `guardrails`, `output`, and `task_type`; an `experiment_card_reference` is optional.
- `done_check` uses an argv command, never a shell string. Shell-control characters and common code-evaluation flags are rejected.
- Production access and irreversible actions are always false in this contract layer.
- Numeric defaults are provisional configuration, not validated operating limits. Raising a default requires a permitted override reason.
- Provenance records every authored field as either human-provided or lead-agent-authored, and records platform-added fields separately.

## Top-level schema

```json
{
  "schema_version": "asdi.run-contract/v1",
  "task_type": "feature",
  "objective": "Non-empty objective",
  "why": "Non-empty reason this work is admitted",
  "constraints": [],
  "out_of_scope": [],
  "done_check": {
    "description": "Human-readable success condition",
    "argv": ["python3", "-m", "pytest", "-q"]
  },
  "boundaries": {
    "protected_paths": ["CODEOWNERS"],
    "max_changed_lines": 400,
    "network": {"mode": "deny_all"},
    "production_access": false,
    "irreversible_actions": false
  },
  "guardrails": {
    "max_turns": 200,
    "max_spend_usd": 8,
    "wall_clock_seconds": 5400
  },
  "output": {"kind": "report"},
  "provenance": {
    "human_provided": ["objective", "why"],
    "lead_agent_authored": ["constraints", "out_of_scope", "done_check"],
    "platform_defaults": ["boundaries", "guardrails", "output", "task_type"]
  }
}
```

`output.kind` may be `pull_request`, `report`, or `artifact`. A `pull_request` output requires a safe Git branch name. An `artifact` output requires a relative output path.

## Provisional defaults

The initial defaults are 200 turns, USD 8, 5,400 seconds, and 400 changed lines. They are intentionally marked provisional and are loaded from one configuration object. They are not evidence-based operating thresholds and do not become approved by use.

Raising any default beyond its configured absolute ceiling is invalid. Raising a default within the ceiling requires `owner_approved`, `charter_approved`, or `safety_review` in the applicable `override_reason` field.

## Validation boundary

`asdi.run_contract.validate_run_contract` returns a defensive copy or raises `RunContractValidationError`. A launcher must call this function and must treat any raised validation error as a durable pre-launch failure. This ticket does not add a launcher, runtime, sandbox, or execution capability.

Validate a fixture with:

```sh
python3 -m asdi.run_contract validate fixtures/run_contracts/valid/default.json
```
