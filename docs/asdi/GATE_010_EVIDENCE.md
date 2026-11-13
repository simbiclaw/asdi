# ASDI-010 Run-Contract Evidence

**Date:** 2026-11-13
**Ticket:** ASDI-010
**Result:** **PASS for contract schema and validator; runtime launch remains disabled**

## Changed paths

| Path | Capability |
|---|---|
| [`src/asdi/run_contract.py`](../../src/asdi/run_contract.py) | Contract constants, adjustable provisional defaults, builder, strict validator, command safety checks, provenance checks, defensive normalization, and validation CLI. |
| [`src/asdi/__init__.py`](../../src/asdi/__init__.py) | Initial package marker. |
| [`fixtures/run_contracts/valid/default.json`](../../fixtures/run_contracts/valid/default.json) | Valid full contract with a safe PR branch and list coverage. |
| [`fixtures/run_contracts/valid/empty_optional_lists.json`](../../fixtures/run_contracts/valid/empty_optional_lists.json) | Explicitly empty constraints and out-of-scope lists. |
| [`fixtures/run_contracts/invalid/`](../../fixtures/run_contracts/invalid/) | Missing objective, missing `done_check`, shell string, unsafe metacharacter, disallowed executable, negative spend, zero wall clock, unsupported output, production access, unapproved override, conflicting/unknown provenance. |
| [`tests/test_run_contract.py`](../../tests/test_run_contract.py) | Builder, valid fixture, defensive copy, invalid fixture, approved override, and CLI behavior tests. |
| [`docs/asdi/RUN_CONTRACT.md`](RUN_CONTRACT.md) | Contract schema and enforcement boundary. |
| [`docs/asdi/decisions/ADR-0005-run-contract-implementation.md`](decisions/ADR-0005-run-contract-implementation.md) | Scoped standard-library implementation decision. |

## Implemented acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| Five authored fields are represented | Pass | `objective`, `why`, `constraints`, `out_of_scope`, and `done_check` are required by the validator and builder. |
| Genuinely absent optional lists are explicit | Pass | Empty `constraints` and `out_of_scope` arrays validate in the valid fixture. |
| Platform defaults are added | Pass | The builder adds boundaries, guardrails, output, task type, optional experiment reference, and corresponding provenance. |
| Numeric defaults are configurable and provisional | Pass | `RunContractConfig` contains the 200 / USD 8 / 5,400 seconds / 400 lines defaults, configurable ceilings, and override rules; documentation marks them provisional. |
| Types and required fields are validated | Pass | Fixtures and tests cover missing fields, non-objects, unsupported values, unknown fields, invalid paths, and invalid provenance partitions. |
| Command safety is validated | Pass | `done_check` must use argv; shell-control/substitution characters, code-evaluation flags, disallowed executables, unsafe cwd, and invalid timeout are rejected. |
| Allowed output kind is validated | Pass | `pull_request`, `report`, and `artifact` are configurable; unsupported kinds fail; PR/artifact-specific fields are required. |
| Permitted override reasons are validated | Pass | Raising a provisional default requires `owner_approved`, `charter_approved`, or `safety_review`; over configured ceilings is always invalid. |
| Provenance is recorded | Pass | Human-provided and lead-agent-authored lists must partition exactly the five authored fields; platform-added fields must be complete and free of duplicates/unknowns. |
| Invalid contract cannot launch a run | Pass in current state | Validation raises before returning a contract. No launcher exists; ADR-0004 also disables runtime launch. A future launcher must invoke validation before run creation. |

## Tests executed

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Result:

```text
Ran 11 tests in 0.572s
OK
```

The suite also invokes the CLI for every valid and invalid fixture and verifies exit codes 0 and 2 respectively.

## Boundary and remaining risk

ASDI-010 does not execute `done_check`, enforce live turn/spend/wall-clock consumption, create a process/container, or prove sandbox isolation. Those are ASDI-011 through ASDI-013. The 400-line diff budget and runtime guardrail defaults remain provisional and unapproved. GitHub-native branch protection is deferred by ADR-0004, so H1 remains unsatisfied and all autonomous execution remains disabled.
